"""Apply numbered data patches through the ingest apply engine.

A *data patch* is a small, source-attributed set of catalog claims authored
as ``NNNN-slug.yaml`` (see ``docs/DataPatches.md``). This command discovers
patches, content-hashes them, consults the per-database applied-ledger
(``IngestRun`` rows carrying a ``patch_id``) and applies the not-yet-applied
ones in numeric order through ``apply_plan`` — the same engine ingest uses.

It is manual and infrequent: no deploy hook, no startup hook.

    uv run python manage.py ingest_patches [--patches-dir DIR]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from django.utils.termcolors import make_style

from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.patches import (
    PATCH_ID_RE,
    PatchError,
    build_plan,
    load_patch,
)
from apps.claim_ingest.plan import RunReport
from apps.provenance.models import IngestRun, Source

# <repo>/data/ingest_sources/flippatch/patches — where pull_patches lands the
# published patch files (authored in the flippatch repo, separate from pindata).
DEFAULT_PATCHES_DIR = (
    Path(__file__).parents[5] / "data" / "ingest_sources" / "flippatch" / "patches"
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

    def handle(
        self,
        *args: object,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        patches_dir = Path(options["patches_dir"])

        if not patches_dir.is_dir():
            # Benign: a fresh DB or a bundle with no patches yet (e.g. before
            # `make pull-patches`). Treated like an empty dir so it's a no-op
            # rather than a hard failure. An empty existing dir is the same
            # no-op below.
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
                report = self._apply_one(path, patch_id)
            except (PatchError, IntegrityError) as exc:
                failed = (patch_id, str(exc))
                self.stdout.write(self.style.ERROR(f"❌ failed {patch_id}"))
                break
            if report is not None:
                applied.append(patch_id)
                src_created += report.sources_created
                src_links += report.source_links_created
                src_skipped += report.sources_skipped
                self.stdout.write(self.style.SUCCESS(f"✓ applied {patch_id}"))
            else:
                skipped.append(patch_id)
                self.stdout.write(
                    self._muted(f"∅ skipped {patch_id} (already applied)")
                )

        # Invalidate cached endpoint data once, at the command level
        # (apply_plan does not invalidate). Needed even for patches with no
        # relationship claims.
        if applied:
            from apps.catalog.cache import invalidate_response_cache

            invalidate_response_cache()

        self._report(
            applied,
            skipped,
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

    def _apply_one(self, path: Path, patch_id: str) -> RunReport | None:
        """Apply one patch. Returns its report, or ``None`` if already applied.

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
                return None  # already applied
            raise PatchError(
                f"{patch_id} was already applied with a different content hash "
                f"— an applied patch is immutable; add a new numbered patch "
                f"instead of editing this one"
            )

        plan = build_plan(doc, source=source, patch_id=patch_id)
        try:
            return apply_plan(plan)
        except IntegrityError:
            # Lost a race: another process applied this patch_id concurrently
            # and the partial unique index rejected our SUCCESS flip. If it's
            # now applied, treat as a skip; otherwise it's a real failure.
            if self._is_applied(patch_id):
                return None
            raise
        except ValidationError as exc:
            # Invalid claim values (bad year/range/type) are normal authoring
            # errors — report them as a patch failure, not a traceback. Full
            # per-claim detail is recorded on the failed IngestRun.errors.
            raise PatchError("; ".join(exc.messages)) from exc

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
        src_created: int = 0,
        src_links: int = 0,
        src_skipped: int = 0,
    ) -> None:
        self.stdout.write(f"\napplied: {len(applied)}  skipped: {len(skipped)}")
        if src_created or src_links or src_skipped:
            self.stdout.write(
                f"citation sources: {src_created} created, "
                f"{src_links} links added, {src_skipped} unchanged"
            )
