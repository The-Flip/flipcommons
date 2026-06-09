"""Apply numbered data patches through the ingest apply engine.

A *data patch* is a small, source-attributed set of catalog claims authored
as ``NNNN-slug.yaml`` (see ``docs/DataPatches.md``). This command discovers
patches, content-hashes them, consults the per-database applied-ledger
(``IngestRun`` rows carrying a ``patch_id``) and applies the not-yet-applied
ones in numeric order through ``apply_plan`` — the same engine ingest uses.

It is manual and infrequent: no deploy hook, no startup hook.

    uv run python manage.py ingest_patches [--patches-dir DIR] [--dry-run]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, NamedTuple

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from django.utils.termcolors import make_style

from apps.catalog.ingestion.apply import RunReport, apply_plan
from apps.catalog.ingestion.patches import (
    PATCH_ID_RE,
    PatchError,
    build_plan,
    load_patch,
)
from apps.provenance.models import IngestRun, Source


class ApplyOutcome(NamedTuple):
    """Result of applying one patch: whether it ran, and its run report.

    ``report`` is ``None`` when the patch was skipped (already in the ledger);
    otherwise it carries the counters the command rolls up for its summary.
    """

    applied: bool
    report: RunReport | None


# <repo>/data/ingest_sources/pindata/patches — where pull_ingest_sources
# lands the published patch files.
DEFAULT_PATCHES_DIR = (
    Path(__file__).parents[5] / "data" / "ingest_sources" / "pindata" / "patches"
)

# Bold black == bright black == gray on most terminals; used to mute the
# already-applied "skipped" lines so applied (green) patches stand out.
_MUTED = make_style(fg="black", opts=("bold",))


class Command(BaseCommand):
    help = "Apply numbered data patches (NNNN-slug.yaml) through the ingest engine."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--patches-dir",
            default=str(DEFAULT_PATCHES_DIR),
            help="Directory of NNNN-slug.yaml patch files.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report intended claims without writing.",
        )

    def handle(
        self,
        *args: object,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        patches_dir = Path(options["patches_dir"])
        dry_run: bool = options["dry_run"]

        if not patches_dir.is_dir():
            # Benign: a fresh DB or a bundle with no patches yet (e.g. before
            # `make pull-ingest`). Treated like an empty dir so chaining this
            # onto full ingest never hard-fails. An empty existing dir is the
            # same no-op below.
            self.stdout.write(f"No patches directory at {patches_dir} — nothing to do")
            return

        paths = self._discover(patches_dir)
        if not paths:
            self.stdout.write(f"No patches found in {patches_dir}")
            return

        applied: list[str] = []
        skipped: list[str] = []
        failed: tuple[str, str] | None = None
        # Roll-up of citation-source side writes across applied patches.
        src_created = src_links = src_skipped = 0

        for path in paths:
            patch_id = path.stem
            try:
                outcome = self._apply_one(path, patch_id, dry_run=dry_run)
            except (PatchError, IntegrityError) as exc:
                failed = (patch_id, str(exc))
                self.stdout.write(self.style.ERROR(f"❌ failed {patch_id}"))
                break
            if outcome.applied:
                applied.append(patch_id)
                if outcome.report is not None:
                    src_created += outcome.report.sources_created
                    src_links += outcome.report.source_links_created
                    src_skipped += outcome.report.sources_skipped
                verb = "would apply" if dry_run else "applied"
                self.stdout.write(self.style.SUCCESS(f"✓ {verb} {patch_id}"))
            else:
                skipped.append(patch_id)
                self.stdout.write(
                    self._muted(f"∅ skipped {patch_id} (already applied)")
                )

        # Invalidate cached endpoint data once, at the command level — the
        # same pattern ingest_all / resolve_claims use (apply_plan does not
        # invalidate). Needed even for patches with no relationship claims.
        if applied and not dry_run:
            from apps.catalog.cache import invalidate_all

            invalidate_all()

        self._report(
            applied,
            skipped,
            dry_run=dry_run,
            src_created=src_created,
            src_links=src_links,
            src_skipped=src_skipped,
        )
        if failed is not None:
            raise CommandError(f"Patch {failed[0]} failed: {failed[1]}")

    def _muted(self, text: str) -> str:
        """Gray styling for skipped lines; identity when color is disabled.

        ``self.style`` is ``no_style()`` (every role an identity function) when
        Django turns color off — ``--no-color``, ``DJANGO_COLORS=nocolor`` or a
        non-TTY stdout. We piggyback on that detection so muted text degrades to
        plain text in the same cases the built-in styles do.
        """
        if self.style.SUCCESS("x") == "x":
            return text
        return _MUTED(text)

    # ── discovery + pre-flight ────────────────────────────────────────

    def _discover(self, patches_dir: Path) -> list[Path]:
        """Return patch paths sorted by numeric prefix; pre-flight the batch.

        Hard-errors (before any patch is applied) on a malformed filename or
        a duplicate numeric prefix — never apply a partial set. The caller has
        already verified the directory exists.
        """
        # Lexical sort == numeric order: the NNNN prefix is always 4 zero-padded
        # digits (enforced below by PATCH_ID_RE), so one sort gives application
        # order and deterministic pre-flight.
        paths = sorted(patches_dir.glob("*.yaml"))
        seen_prefixes: dict[str, str] = {}
        for path in paths:
            if not PATCH_ID_RE.match(path.stem):
                raise CommandError(
                    f"Bad patch filename {path.name!r}: must be NNNN-slug.yaml"
                )
            prefix = path.stem.split("-", 1)[0]
            if prefix in seen_prefixes:
                raise CommandError(
                    f"Duplicate patch number {prefix!r}: "
                    f"{seen_prefixes[prefix]!r} and {path.name!r}"
                )
            seen_prefixes[prefix] = path.name

        return paths

    # ── per-patch ─────────────────────────────────────────────────────

    def _apply_one(self, path: Path, patch_id: str, *, dry_run: bool) -> ApplyOutcome:
        """Apply one patch. Returns an :class:`ApplyOutcome` (applied + report).

        Raises ``PatchError`` on a patch-level hard error (missing attribution
        Source, immutability mismatch, adapter failure) — the caller turns it
        into the failed-run report.
        """
        doc = load_patch(path.read_text(encoding="utf-8"))

        try:
            source = Source.objects.get(slug=doc.attribution)
        except Source.DoesNotExist:
            raise PatchError(
                f"attribution Source {doc.attribution!r} does not exist"
            ) from None

        # Ledger: a SUCCESS run with this patch_id means it's applied here.
        prior = IngestRun.objects.filter(
            patch_id=patch_id, status=IngestRun.Status.SUCCESS
        ).first()
        if prior is not None:
            if prior.input_fingerprint == doc.fingerprint:
                return ApplyOutcome(applied=False, report=None)  # already applied
            raise PatchError(
                f"{patch_id} was already applied with a different content hash "
                f"— an applied patch is immutable; add a new numbered patch "
                f"instead of editing this one"
            )

        plan = build_plan(doc, source=source, patch_id=patch_id)
        try:
            report = apply_plan(plan, dry_run=dry_run)
        except IntegrityError:
            # Lost a race: another process applied this patch_id concurrently
            # and the partial unique index rejected our SUCCESS flip. If it's
            # now applied, treat as a skip; otherwise it's a real failure.
            if not dry_run and self._is_applied(patch_id):
                return ApplyOutcome(applied=False, report=None)
            raise
        except ValidationError as exc:
            # Invalid claim values (bad year/range/type) are normal authoring
            # errors — report them as a patch failure, not a traceback. Full
            # per-claim detail is recorded on the failed IngestRun.errors.
            raise PatchError("; ".join(exc.messages)) from exc
        return ApplyOutcome(applied=True, report=report)

    @staticmethod
    def _is_applied(patch_id: str) -> bool:
        return IngestRun.objects.filter(
            patch_id=patch_id, status=IngestRun.Status.SUCCESS
        ).exists()

    # ── reporting ─────────────────────────────────────────────────────

    def _report(
        self,
        applied: list[str],
        skipped: list[str],
        *,
        dry_run: bool,
        src_created: int = 0,
        src_links: int = 0,
        src_skipped: int = 0,
    ) -> None:
        prefix = "[dry-run] " if dry_run else ""
        verb = "would apply" if dry_run else "applied"
        self.stdout.write(f"\n{prefix}{verb}: {len(applied)}  skipped: {len(skipped)}")
        if src_created or src_links or src_skipped:
            self.stdout.write(
                f"{prefix}citation sources: {src_created} created, "
                f"{src_links} links added, {src_skipped} unchanged"
            )
