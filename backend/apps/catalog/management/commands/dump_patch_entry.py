"""Rehydrate a catalog entity's markdown fields as a runnable data-patch entry.

Emits a complete patch document (``attribution:`` + a single ``claims:`` entry)
carrying the entity's current markdown fields in **authoring** format
(``[[cite:<slug>]]``), so the generation pipeline or a human can reword one
sentence and resubmit with every untouched citation intact.

Re-applying the unedited dump is a no-op: existing slugs self-resolve to the
same ``[[cite:id:<pk>]]`` storage, so the diff is empty and nothing is minted —
*provided* the patch is attributed to the source that owns the field's winning
claim, because ``_diff_claims`` compares only against active claims from the same
source. The command therefore defaults ``attribution:`` to that owning source;
``--attribution`` overrides it, which **forks** the text into a new
source-owned claim (resolved against the original by priority) rather than
preserving no-op semantics.

A description edited interactively in-app is owned by a ``user`` (``source`` is
null), and a source-attributed patch cannot faithfully reproduce it — so a
user-owned winning claim is an error unless ``--attribution`` is supplied.
"""

from __future__ import annotations

from typing import NamedTuple

import yaml
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.catalog.models import CatalogModel
from apps.core.entity_types import get_linkable_model
from apps.core.markdown import convert_storage_to_authoring, get_markdown_fields
from apps.provenance.helpers import active_claims, claims_prefetch
from apps.provenance.models import Claim, Source


class _LiteralStr(str):
    """A string the dumper must render as a literal (``|``) block scalar.

    Scoping the literal-block style to this wrapper keeps it off the plain
    scalars (the ``attribution`` value, the ``type.public_id`` key) that must
    stay unquoted.
    """


class _PatchDumper(yaml.SafeDumper):
    """SafeDumper with a literal-block representer for ``_LiteralStr`` only."""


def _represent_literal(dumper: _PatchDumper, data: _LiteralStr) -> yaml.ScalarNode:
    # ``style='|'`` is a hint: PyYAML's scalar analysis silently falls back to
    # double-quoted when the text has trailing whitespace on a line (markdown
    # hard breaks), blank-only/leading-space lines or tabs. The fallback still
    # round-trips byte-for-byte through the loader — only readability degrades.
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


_PatchDumper.add_representer(_LiteralStr, _represent_literal)


class _EmittedField(NamedTuple):
    """One markdown field's authoring text and the source that owns it."""

    field: str
    text: str
    source: Source | None


class Command(BaseCommand):
    help = (
        "Dump a catalog entity's markdown fields as a runnable patch entry "
        "(authoring-format text, real citation slugs in place)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "entity_ref",
            help="Entity reference as 'type.public_id' (e.g. model.mazatron).",
        )
        parser.add_argument(
            "--attribution",
            default=None,
            help=(
                "Source slug to attribute the patch to. Defaults to the source "
                "that owns the field's winning claim. Overriding forks the text "
                "into a new source-owned claim (not a no-op)."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        entity_ref = str(options["entity_ref"])
        attribution_opt = options["attribution"]
        attribution = str(attribution_opt) if attribution_opt is not None else None

        model_class, public_id = _resolve(entity_ref)
        markdown_fields = get_markdown_fields(model_class)
        if not markdown_fields:
            raise CommandError(
                f"{entity_ref}: {model_class.entity_type!r} has no markdown fields"
            )

        obj = (
            model_class._default_manager.prefetch_related(
                claims_prefetch(field_names=markdown_fields)
            )
            .filter(**{model_class.public_id_field: public_id})
            .first()
        )
        if obj is None:
            raise CommandError(
                f"{entity_ref}: no such {model_class.entity_type} {public_id!r}"
            )

        emitted = _collect_fields(obj, markdown_fields)
        if not emitted:
            raise CommandError(f"{entity_ref}: no markdown content to dump")

        attribution = attribution or _default_attribution(entity_ref, emitted)

        ref = f"{model_class.entity_type}.{public_id}"
        document = {
            "attribution": attribution,
            "claims": [{ref: {e.field: _LiteralStr(e.text) for e in emitted}}],
        }
        self.stdout.write(
            yaml.dump(
                document,
                Dumper=_PatchDumper,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
                width=1_000_000,  # never line-wrap plain scalars
            ),
            ending="",
        )


def _resolve(entity_ref: str) -> tuple[type[CatalogModel], str]:
    """Resolve ``type.public_id`` to its concrete catalog model + public id."""
    entity_type, _, public_id = entity_ref.partition(".")
    if not entity_type or not public_id:
        raise CommandError(
            f"{entity_ref!r} must be 'type.public_id' (e.g. model.mazatron)"
        )
    try:
        model_class = get_linkable_model(entity_type)
    except ValueError as exc:
        raise CommandError(f"{entity_ref}: {exc}") from exc
    if not issubclass(model_class, CatalogModel):
        raise CommandError(f"{entity_ref}: {entity_type!r} is not a catalog entity")
    return model_class, public_id


def _collect_fields(
    obj: CatalogModel, markdown_fields: list[str]
) -> list[_EmittedField]:
    """Authoring text + owning source for each non-empty markdown field.

    The authoring text is the materialized storage value run through
    ``convert_storage_to_authoring`` — the exact inverse a re-apply runs, so an
    unedited dump round-trips to byte-identical storage. Call it **directly**,
    not via ``build_rich_text(...).text``: that round-trip inverse is the
    contract, not the edit form's schema builder, which could grow text
    normalization that would silently break byte-identity. Fields no claim has
    set (empty value) are skipped.
    """
    active = active_claims(obj)
    emitted: list[_EmittedField] = []
    for field in markdown_fields:
        stored = getattr(obj, field) or ""
        if not stored:
            continue
        text = convert_storage_to_authoring(stored)
        emitted.append(_EmittedField(field, text, _winning_source(active, field)))
    return emitted


def _default_attribution(entity_ref: str, emitted: list[_EmittedField]) -> str:
    """The slug of the source owning every emitted field's winning claim.

    A field with no owning source (its winning claim is user-authored, or its
    source is disabled and so excluded from the prefetch) or fields owned by
    differing sources have no single attribution — both demand an explicit
    ``--attribution``.
    """
    sources = {e.source for e in emitted}
    if None in sources:
        raise CommandError(
            f"{entity_ref}: a winning markdown claim has no owning source "
            f"(user-authored, or its source is disabled); pass --attribution "
            f"<slug> to fork it into a source-owned claim (not a faithful no-op)."
        )
    slugs = {source.slug for source in sources if source is not None}
    if len(slugs) > 1:
        raise CommandError(
            f"{entity_ref}: markdown fields are owned by different sources "
            f"({', '.join(sorted(slugs))}); pass --attribution <slug>."
        )
    return slugs.pop()


def _winning_source(active: list[Claim], field: str) -> Source | None:
    """The source of the winning (highest-priority) claim for ``field``.

    ``active`` is ordered by claim_key, -priority, -created_at, so the first
    claim for the field is the winner. Returns ``None`` when it is user-authored.
    """
    for claim in active:
        if claim.field_name == field:
            return claim.source
    return None
