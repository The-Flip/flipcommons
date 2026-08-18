"""Generate scripts/analysis/sql/entity_registry.sql from linkable models.

The analytics layer's copy of the entity registry. Two DuckDB objects:

- ``entity_registry``: one row per entity, carrying every identity fact the
  model declares — ``entity_type`` and its plural, the content-type label, the
  table and the ``public_id_field``. Translates the public vocabulary to the
  two Django-internal spellings SQL can see.
- ``entity_subjects``: one row per ``ClaimControlledModel`` entity, keyed
  ``(subject_type, subject_id)``.
- ``entity_prose``: one row per (live entity, markdown field), the authored-prose
  corpus. Its field set comes from :func:`apps.core.markdown.get_markdown_fields`,
  the same ``MarkdownField`` introspection the save path uses, so a second prose
  field on any model joins the corpus with no SQL edit.

All three are generated because SQL cannot iterate table names, so adding an
entity needs no SQL edit.

Run via ``make codegen``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Model

from apps.core.entity_types import all_linkable_models
from apps.core.markdown import get_markdown_fields
from apps.core.models import LifecycleStatusModel, LinkableModel
from apps.core.wikilinks import WikilinkableModel
from apps.provenance.models import ClaimControlledModel

OUTPUT_PATH = "scripts/analysis/sql/entity_registry.sql"


class EntityRow(NamedTuple):
    """One entity's identity across the three vocabularies SQL has to bridge."""

    entity_type: str
    entity_type_plural: str
    django_label: str
    db_table: str
    public_id_field: str
    is_subject: bool
    # The model's ``MarkdownField`` names, in declaration order; empty for an
    # entity that authors no prose.
    prose_fields: tuple[str, ...]
    # Whether prose may wikilink this entity at all — `WikilinkableModel`
    # membership, which is narrower than `LinkableModel`. Location is
    # URL-addressable but absent from the picker, so an analysis that treats
    # every entity as linkable reports unlinked mentions nobody can act on.
    is_wikilinkable: bool


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
    pid_width = max(len(_sql_str(r.public_id_field)) for r in rows)
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
            _sql_str(r.public_id_field).ljust(pid_width),
            "true " if r.is_wikilinkable else "false",
        ]
        tail = "" if i == len(rows) - 1 else ","
        lines.append(f"    ({', '.join(cells)}){tail}")
    lines += [
        "  ) AS t(entity_type, entity_type_plural, django_label, db_table,"
        " public_id_field, is_wikilinkable);",
        "COMMENT ON VIEW entity_registry IS",
        "  'One row per catalog entity type — the entity_type this layer speaks and its"
        " plural, and the content-type label, table name and public id field the"
        " physical schema speaks. is_wikilinkable says whether prose may link it at all"
        " (Location cannot). Join it to fc.django_content_type to decode a polymorphic"
        " reference; _entity_type_of(table) spells a single one.';",
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


def _prose_view(rows: list[EntityRow]) -> list[str]:
    branches = [(r, f) for r in rows if r.prose_fields for f in sorted(r.prose_fields)]
    type_width = max(len(_sql_str(r.entity_type)) for r, _ in branches)
    field_width = max(len(_sql_str(f)) for _, f in branches)
    lines = [
        "CREATE OR REPLACE VIEW entity_prose AS",
        "  SELECT * FROM (",
    ]
    for i, (r, field) in enumerate(branches):
        # Only the leading branch names the output columns; the rest are positional.
        first = i == 0
        lead = " " * len("UNION ALL ") if first else "UNION ALL "
        etype = _sql_str(r.entity_type).ljust(type_width)
        fname = _sql_str(field).ljust(field_width)
        head = f"{etype} AS entity_type" if first else etype
        pid = f"{r.public_id_field} AS public_id" if first else r.public_id_field
        col = f"{fname} AS field" if first else fname
        text = f"{field} AS text" if first else field
        lines.append(
            # S608: see _subjects_view. Interpolated parts are `_meta.db_table`,
            # `public_id_field` and MarkdownField names off the model class.
            f"    {lead}SELECT {head}, id, {pid}, {col}, {text}"  # noqa: S608
            f" FROM _staging('fc.{r.db_table}')"
        )
    lines += [
        "  ) AS t(entity_type, entity_id, public_id, field, text);",
        "COMMENT ON VIEW entity_prose IS",
        "  'One row per LIVE entity per markdown field, of ANY entity type — the"
        " authored-prose corpus. For questions that SPAN entity types; a question about"
        " one type reads that entity view, which carries description already. text IS"
        " NULL where the field is unset, and every MarkdownField is a row, so predicate"
        " on `field` rather than assuming description.';",
    ]
    return lines


class AliasRow(NamedTuple):
    """One concrete ``AliasModel``, reduced to what the SQL branch needs."""

    entity_type: str
    db_table: str
    fk_column: str


def _alias_rows() -> list[AliasRow]:
    """Every registered alias type, from the engine's own registry.

    ``discover_alias_types`` is the canonical reader — it already resolved each
    alias model's parent FK by introspection, and its module docstring asks
    consumers not to re-derive that. Walking ``AliasModel.__subclasses__()``
    here would be a second, drifting answer to a question the engine settled.
    """
    from apps.catalog.engine.aliases import discover_alias_types

    rows = [
        AliasRow(
            entity_type=_require_linkable(a.parent_model).entity_type,
            db_table=a.alias_model._meta.db_table,
            fk_column=f"{a.fk_name}_id",
        )
        for a in discover_alias_types()
    ]
    if not rows:
        raise CommandError(
            "No alias types registered — the catalog AppConfig.ready never ran."
        )
    return sorted(rows)


def _require_linkable(model: type[Model]) -> type[LinkableModel]:
    """Narrow an alias parent to the base that actually declares ``entity_type``.

    The alias registry types a parent as ``ClaimControlledModel``, which is the
    wider guarantee — it says the entity carries claims, not that it has a public
    entity type. ``entity_aliases`` keys on ``entity_type``, so a parent without
    one has nothing to key by, and failing here beats emitting SQL that cannot
    bind.
    """
    if not issubclass(model, LinkableModel):
        raise CommandError(
            f"{model.__name__} has aliases but is not a LinkableModel, so it has "
            "no entity_type for entity_aliases to key on."
        )
    return model


def _aliases_view(rows: list[AliasRow]) -> list[str]:
    type_width = max(len(_sql_str(r.entity_type)) for r in rows)
    fk_width = max(len(r.fk_column) for r in rows)
    lines = [
        "CREATE OR REPLACE VIEW entity_aliases AS",
        "  SELECT * FROM (",
    ]
    for i, r in enumerate(rows):
        # Only the leading branch names the output columns; the rest are positional.
        first = i == 0
        lead = " " * len("UNION ALL ") if first else "UNION ALL "
        etype = _sql_str(r.entity_type).ljust(type_width)
        head = f"{etype} AS entity_type" if first else etype
        fk = r.fk_column.ljust(fk_width)
        eid = f"{fk} AS entity_id" if first else fk
        value = "value AS alias" if first else "value"
        lines.append(
            # S608: see _subjects_view. Interpolated parts are `_meta.db_table` and the
            # parent FK name, both off the model class.
            f"    {lead}SELECT {head}, {eid}, {value} FROM fc.{r.db_table}"  # noqa: S608
        )
    lines += [
        "  ) AS t(entity_type, entity_id, alias);",
        "COMMENT ON VIEW entity_aliases IS",
        "  'One row per alias of ANY entity type, keyed (entity_type, entity_id) to match"
        " entity_subjects — the alternate names prose might use. NOT live-filtered and it"
        " carries no parent name: join entity_subjects for liveness, public id and the"
        " canonical name. The per-type views (theme_aliases, person_aliases, …) stay the"
        " way to ask about ONE type, since they decode the parent slug.';",
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
            prose_fields = tuple(get_markdown_fields(cls))
            # Fail here rather than let generated SQL fail far from the model change.
            if is_subject:
                _require_columns(cls, {cls.public_id_field, "name"})
                _require_lifecycle(cls)
            # entity_prose reads through _staging(), which selects `status` away, so a
            # branch for a model without a lifecycle would fail to bind.
            if prose_fields:
                _require_lifecycle(cls)
            rows.append(
                EntityRow(
                    entity_type=cls.entity_type,
                    entity_type_plural=cls.entity_type_plural,
                    django_label=cls._meta.label_lower,
                    db_table=cls._meta.db_table,
                    public_id_field=cls.public_id_field,
                    is_subject=is_subject,
                    prose_fields=prose_fields,
                    is_wikilinkable=issubclass(cls, WikilinkableModel),
                )
            )
        rows.sort(key=lambda r: r.entity_type)
        if not any(r.is_subject for r in rows):
            raise CommandError("No ClaimControlledModel entities found.")
        if not any(r.prose_fields for r in rows):
            raise CommandError("No linkable entity declares a MarkdownField.")

        lines = [
            "-- Generated by: python manage.py export_entity_registry",
            "-- Do not edit manually — edit the models and re-run `make codegen`.",
            "--",
            "-- Why no view here spells an entity type the way Django stores it:",
            "-- `LinkableModel.entity_type` is the canonical public name ('model',",
            "-- 'person'), a content type row spells the same thing",
            "-- 'catalog.machinemodel', and no string rule turns one into the other.",
            "--",
            "-- SQL rather than a data file because the polymorphic unions below need",
            "-- generated table names, which no runtime read of JSON could supply.",
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
            "-- entity_prose — the authored-prose corpus, one row per (entity, markdown",
            "-- field). Which fields those are comes from MarkdownField introspection, so",
            "-- this tracks the save path rather than restating it.",
            "--",
            "-- LIVE-FILTERED, unlike entity_subjects: a soft-deleted record's prose is not",
            "-- catalog content, and no consumer resolving a reference reads it. Reading",
            "-- through _staging() also folds '' to NULL, so an unset field is NULL whichever",
            "-- spelling Django stored.",
            *_prose_view(rows),
            "",
            "-- entity_aliases — every alternate name, of any entity type, in one relation.",
            "-- Driven from the engine's alias registry, which already resolved each alias",
            "-- model's parent FK, so a new AliasModel joins the view with no SQL edit.",
            "--",
            "-- NOT LIVE-FILTERED and no parent name, for the same reason entity_subjects",
            "-- carries a status instead of a filter: the join that supplies liveness also",
            "-- supplies the name and public id, so doing it here would mean doing it twice.",
            *_aliases_view(_alias_rows()),
            "",
        ]

        output_path = Path(settings.BASE_DIR).parent / OUTPUT_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines))
