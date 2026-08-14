"""Generate scripts/analysis/entity_registry.sql from linkable models.

The analytics layer's copy of the entity registry. Two DuckDB objects:

- ``entity_registry``: one row per entity, carrying every identity fact the
  model declares — ``entity_type`` and its plural, the content-type label, the
  table and the ``public_id_field``. Translates the public vocabulary to the
  two Django-internal spellings SQL can see.
- ``entity_subjects``: one row per ``ClaimControlledModel`` entity, keyed
  ``(subject_type, subject_id)``. Generated because SQL cannot iterate table
  names, so adding an entity needs no SQL edit.

Run via ``make codegen``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Model

from apps.core.entity_types import all_linkable_models
from apps.core.models import LifecycleStatusModel
from apps.provenance.models import ClaimControlledModel

OUTPUT_PATH = "scripts/analysis/entity_registry.sql"


class EntityRow(NamedTuple):
    """One entity's identity across the three vocabularies SQL has to bridge."""

    entity_type: str
    entity_type_plural: str
    django_label: str
    db_table: str
    public_id_field: str
    is_subject: bool


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_columns(cls: type[Model], required: set[str]) -> None:
    """Refuse to emit a subject branch that would not bind."""
    missing = sorted(required - {f.name for f in cls._meta.get_fields()})
    if missing:
        raise CommandError(
            f"{cls.__name__} is a claim subject but has no "
            f"{', '.join(missing)} field. A branch for "
            f"{cls._meta.db_table} would emit SQL that fails to bind."
        )


def _require_lifecycle(cls: type[Model]) -> None:
    """Refuse to emit a subject branch with no lifecycle for ``subject_status``.

    ``LinkableClaimModel`` discovers lifecycle rather than binding it, so a
    claim subject without one is legal.
    """
    if not issubclass(cls, LifecycleStatusModel):
        raise CommandError(
            f"{cls.__name__} is a claim subject but is not a LifecycleStatusModel, "
            f"so it has no entity lifecycle for `subject_status` to carry."
        )


def _registry_view(rows: list[EntityRow]) -> list[str]:
    widths = [
        max(len(_sql_str(getattr(r, f))) for r in rows)
        for f in ("entity_type", "entity_type_plural", "django_label", "db_table")
    ]
    lines = [
        "CREATE OR REPLACE VIEW entity_registry AS",
        "  SELECT * FROM (VALUES",
    ]
    for i, r in enumerate(rows):
        cells = [
            _sql_str(r.entity_type).ljust(widths[0]),
            _sql_str(r.entity_type_plural).ljust(widths[1]),
            _sql_str(r.django_label).ljust(widths[2]),
            _sql_str(r.db_table).ljust(widths[3]),
            _sql_str(r.public_id_field),
        ]
        tail = "" if i == len(rows) - 1 else ","
        lines.append(f"    ({', '.join(cells)}){tail}")
    lines += [
        "  ) AS t(entity_type, entity_type_plural, django_label, db_table,"
        " public_id_field);",
        "COMMENT ON VIEW entity_registry IS",
        "  'One row per catalog entity type — the entity_type this layer speaks and its"
        " plural, and the content-type label, table name and public id field the"
        " physical schema speaks. Join it to fc.django_content_type to decode a"
        " polymorphic reference; entity_type_of(table) spells a single one.';",
    ]
    return lines


def _subjects_view(rows: list[EntityRow]) -> list[str]:
    subjects = [r for r in rows if r.is_subject]
    width = max(len(_sql_str(r.entity_type)) for r in subjects)
    lines = [
        "CREATE OR REPLACE VIEW entity_subjects AS",
        "  SELECT",
        "    subject_type,",
        "    id        AS subject_id,",
        "    public_id AS subject_public_id,",
        "    name      AS subject_name,",
        "    status    AS subject_status",
        "  FROM (",
    ]
    for i, r in enumerate(subjects):
        # Only the leading branch names the output columns; the rest are positional.
        first = i == 0
        lead = " " * len("UNION ALL ") if first else "UNION ALL "
        name = _sql_str(r.entity_type).ljust(width)
        head = f"{name} AS subject_type" if first else name
        pid = f"{r.public_id_field} AS public_id" if first else r.public_id_field
        lines.append(
            # S608 reads any f-string containing SELECT as query construction. This is a
            # code generator: the interpolated parts are `_meta.db_table` and
            # `public_id_field` off the model class, and nothing here executes the text.
            f"    {lead}SELECT {head}, id, {pid}, name, status FROM fc.{r.db_table}"  # noqa: S608
        )
    lines += [
        "  );",
        "COMMENT ON VIEW entity_subjects IS",
        "  'One row per catalog entity of ANY type, keyed (subject_type, subject_id)"
        " the way a polymorphic reference names it — public id, name and status for"
        " resolving a claim, changeset or patch entry subject without branching on its"
        " type. NOT live-filtered; predicate on subject_status.';",
    ]
    return lines


class Command(BaseCommand):
    help = f"Generate {OUTPUT_PATH} from linkable models."

    def handle(
        self,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        rows: list[EntityRow] = []
        for cls in all_linkable_models():
            is_subject = issubclass(cls, ClaimControlledModel)
            # Fail here rather than let generated SQL fail far from the model change.
            if is_subject:
                _require_columns(cls, {cls.public_id_field, "name"})
                _require_lifecycle(cls)
            rows.append(
                EntityRow(
                    entity_type=cls.entity_type,
                    entity_type_plural=cls.entity_type_plural,
                    django_label=cls._meta.label_lower,
                    db_table=cls._meta.db_table,
                    public_id_field=cls.public_id_field,
                    is_subject=is_subject,
                )
            )
        rows.sort(key=lambda r: r.entity_type)
        if not any(r.is_subject for r in rows):
            raise CommandError("No ClaimControlledModel entities found.")

        lines = [
            "-- Generated by: python manage.py export_entity_registry",
            "-- Do not edit manually — edit the models and re-run `make codegen`.",
            "--",
            "-- Why no view here spells an entity type the way Django stores it:",
            "-- `LinkableModel.entity_type` is the canonical public name ('model',",
            "-- 'person'), a content type row spells the same thing",
            "-- 'catalog.machinemodel', and no string rule turns one into the other.",
            "--",
            "-- SQL rather than a data file because `entity_subjects` needs generated",
            "-- table names, which no runtime read of JSON could supply.",
            "",
            *_registry_view(rows),
            "",
            "-- entity_subjects — the polymorphic-reference resolver. `subject_public_id`",
            "-- is NOT a slug: it is whatever the model declares as `public_id_field`,",
            "-- `location_path` for Location, where live places share the slug `victoria`.",
            "--",
            "-- Restricted to `ClaimControlledModel`: a provenance entity (Actor,",
            "-- ChangeSet, Source) is never a claim subject.",
            "--",
            "-- NOT LIVE-FILTERED: dropping a soft-deleted row would turn a retired subject",
            "-- into an unresolvable one. Predicate on `subject_status`.",
            *_subjects_view(rows),
            "",
        ]

        output_path = Path(settings.BASE_DIR).parent / OUTPUT_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines))
