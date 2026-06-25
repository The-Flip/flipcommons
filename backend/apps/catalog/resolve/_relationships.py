"""Resolution logic for relationship claims (credits, themes, gameplay features, tags,
abbreviations).

Includes both single-object and bulk variants for each relationship type.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NamedTuple, cast

from django.db.models import Model

from apps.provenance.claim_presence import member_is_present
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.validation import (
    get_display_override,
    get_relationship_schema,
)

from ..engine.aliases import alias_type_for, discover_alias_types
from ..models import (
    CatalogModel,
    CorporateEntity,
    CorporateEntityLocation,
    Credit,
    CreditRole,
    GameplayFeature,
    Location,
    MachineModel,
    MachineModelGameplayFeature,
    Manufacturer,
    ModelAbbreviation,
    Person,
    RewardType,
    Series,
    Tag,
    Theme,
    Title,
    TitleAbbreviation,
)
from ._claim_values import (
    AbbreviationClaimValue,
    AliasClaimValue,
    CreditClaimValue,
    GameplayFeatureClaimValue,
    LocationClaimValue,
    ParentClaimValue,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Shared tuple shapes
# ------------------------------------------------------------------


class ClaimDedupKey(NamedTuple):
    """Dedup key when picking first-winner-per-claim_key for an entity."""

    object_id: int
    claim_key: str


class CreditAssignment(NamedTuple):
    """A (person, role) pair materialised into a Credit row."""

    person_id: int
    role_id: int


# ------------------------------------------------------------------
# M2M relationship registry
# ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class M2MFieldSpec:
    """Descriptor for a simple M2M relationship resolved from claims."""

    field_name: str  # claim field_name (also the value dict key): "theme", "tag"
    m2m_attr: str  # model attribute: "themes", "tags", "gameplay_features"
    target_model: type[CatalogModel]  # Theme, Tag, GameplayFeature


M2M_FIELDS: dict[str, M2MFieldSpec] = {
    "theme": M2MFieldSpec("theme", "themes", Theme),
    "reward_type": M2MFieldSpec("reward_type", "reward_types", RewardType),
    "tag": M2MFieldSpec("tag", "tags", Tag),
}


# ------------------------------------------------------------------
# Generic M2M resolvers
# ------------------------------------------------------------------


def _resolve_machine_model_m2m(
    spec: M2MFieldSpec,
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Bulk-resolve M2M claims into through-table rows for the given spec."""
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(MachineModel)

    # Pre-fetch active claims with priority annotation.
    claims_qs = Claim.objects.filter(content_type=ct, field_name=spec.field_name)
    if subject_ids is not None:
        claims_qs = claims_qs.filter(object_id__in=subject_ids)
    claims = ranked_claims(claims_qs, "object_id", "claim_key")

    # Pick winner per (object_id, claim_key).
    winners_by_model: dict[int, list[Claim]] = {}
    seen: set[ClaimDedupKey] = set()
    for claim in claims:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners_by_model.setdefault(claim.object_id, []).append(claim)

    # Valid PKs for existence check against stale claims.
    valid_pks = set(spec.target_model._default_manager.values_list("pk", flat=True))

    # Desired PKs from winning claims.
    desired_by_model: dict[int, set[int]] = {}
    for model_id, claims_list in winners_by_model.items():
        desired: set[int] = set()
        for claim in claims_list:
            val = cast(Mapping[str, object], claim.value)
            if not member_is_present(claim):
                continue
            target_pk = val.get(spec.field_name)
            if type(target_pk) is not int or target_pk not in valid_pks:
                logger.warning(
                    "Unresolved %s pk %r in claim (model pk=%s)",
                    spec.field_name,
                    target_pk,
                    model_id,
                )
                continue
            desired.add(target_pk)
        desired_by_model[model_id] = desired

    # Pre-fetch existing M2M through-table rows.
    if subject_ids is not None:
        all_model_ids = subject_ids
    else:
        all_model_ids = set(MachineModel.objects.values_list("pk", flat=True))
    through: type[Model] = getattr(MachineModel, spec.m2m_attr).through
    target_model_name = spec.target_model._meta.model_name
    assert target_model_name is not None
    target_col = target_model_name + "_id"

    existing_by_model: dict[int, set[int]] = {}
    for row in through._default_manager.filter(
        machinemodel_id__in=all_model_ids
    ).values_list("machinemodel_id", target_col):
        existing_by_model.setdefault(row[0], set()).add(row[1])

    # Diff and apply.
    to_create = []
    to_delete_pks: list[int] = []

    for model_id in all_model_ids:
        desired = desired_by_model.get(model_id, set())
        existing = existing_by_model.get(model_id, set())

        for target_pk in desired - existing:
            to_create.append(
                through(machinemodel_id=model_id, **{target_col: target_pk})
            )

    # Build a lookup for deletions.
    for row in through._default_manager.filter(
        machinemodel_id__in=all_model_ids
    ).values_list("pk", "machinemodel_id", target_col):
        pk, model_id, fk_id = row
        desired = desired_by_model.get(model_id, set())
        if fk_id not in desired:
            to_delete_pks.append(pk)

    if to_delete_pks:
        through._default_manager.filter(pk__in=to_delete_pks).delete()
    if to_create:
        through._default_manager.bulk_create(to_create, batch_size=2000)


# ------------------------------------------------------------------
# Public M2M wrappers (single-object)
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Public M2M wrappers (bulk)
# ------------------------------------------------------------------


def resolve_all_themes(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    _resolve_machine_model_m2m(M2M_FIELDS["theme"], subject_ids=subject_ids)


def resolve_all_gameplay_features(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Bulk-resolve gameplay feature claims into through-model rows with counts."""
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(MachineModel)

    claims_qs = Claim.objects.filter(content_type=ct, field_name="gameplay_feature")
    if subject_ids is not None:
        claims_qs = claims_qs.filter(object_id__in=subject_ids)
    claims = ranked_claims(claims_qs, "object_id", "claim_key")

    # Pick winner per (object_id, claim_key).
    winners_by_model: dict[int, list[Claim]] = {}
    seen: set[ClaimDedupKey] = set()
    for claim in claims:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners_by_model.setdefault(claim.object_id, []).append(claim)

    # Valid PKs for existence check against stale claims.
    valid_pks = set(GameplayFeature.objects.values_list("pk", flat=True))

    # Desired (feature_pk, count) from winning claims.
    desired_by_model: dict[int, dict[int, int | None]] = {}
    for mid, claims_list in winners_by_model.items():
        desired: dict[int, int | None] = {}
        for claim in claims_list:
            val = cast(GameplayFeatureClaimValue, claim.value)
            if not member_is_present(claim):
                continue
            feature_pk = val.get("gameplay_feature")
            if feature_pk not in valid_pks:
                logger.warning(
                    "Unresolved gameplay_feature pk %r in claim (model pk=%s)",
                    feature_pk,
                    mid,
                )
                continue
            desired[feature_pk] = val.get("count")
        desired_by_model[mid] = desired

    # Pre-fetch existing through-table rows.
    if subject_ids is not None:
        all_model_ids = subject_ids
    else:
        all_model_ids = set(MachineModel.objects.values_list("pk", flat=True))
    existing_by_model: dict[int, dict[int, tuple[int, int | None]]] = {}
    for row in MachineModelGameplayFeature.objects.filter(
        machinemodel_id__in=all_model_ids
    ).values_list("pk", "machinemodel_id", "gameplayfeature_id", "count"):
        pk, mid, fk_id, count = row
        existing_by_model.setdefault(mid, {})[fk_id] = (pk, count)

    # Diff and apply.
    to_create: list[MachineModelGameplayFeature] = []
    to_delete_pks: list[int] = []
    to_update: list[tuple[int, int | None]] = []  # (pk, new_count)

    for mid in all_model_ids:
        desired = desired_by_model.get(mid, {})
        existing = existing_by_model.get(mid, {})

        for feature_pk, count in desired.items():
            if feature_pk not in existing:
                to_create.append(
                    MachineModelGameplayFeature(
                        machinemodel_id=mid,
                        gameplayfeature_id=feature_pk,
                        count=count,
                    )
                )
            else:
                row_pk, existing_count = existing[feature_pk]
                if existing_count != count:
                    to_update.append((row_pk, count))

        for feature_pk, (row_pk, _) in existing.items():
            if feature_pk not in desired:
                to_delete_pks.append(row_pk)

    if to_delete_pks:
        MachineModelGameplayFeature.objects.filter(pk__in=to_delete_pks).delete()
    if to_create:
        MachineModelGameplayFeature.objects.bulk_create(to_create, batch_size=2000)
    if to_update:
        rows = MachineModelGameplayFeature.objects.in_bulk([pk for pk, _ in to_update])
        for pk, count in to_update:
            mgf_row = rows[pk]
            mgf_row.count = count
        MachineModelGameplayFeature.objects.bulk_update(
            list(rows.values()), ["count"], batch_size=2000
        )


def resolve_all_reward_types(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    _resolve_machine_model_m2m(M2M_FIELDS["reward_type"], subject_ids=subject_ids)


def resolve_all_tags(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    _resolve_machine_model_m2m(M2M_FIELDS["tag"], subject_ids=subject_ids)


# ------------------------------------------------------------------
# Credits (compound identity — not amenable to generic M2M)
# ------------------------------------------------------------------


def resolve_all_credits(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Bulk-resolve MachineModel credit claims into Credit rows."""
    _resolve_credits(MachineModel, "model", subject_ids=subject_ids)


def resolve_all_series_credits(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Bulk-resolve Series credit claims into Credit rows."""
    _resolve_credits(Series, "series", subject_ids=subject_ids)


def _resolve_credits(
    subject_model: type[ClaimControlledModel],
    fk_field: Literal["model", "series"],
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Subject-agnostic core for bulk credit resolution.

    Shared by the MachineModel and Series passes. ``fk_field`` is the ``Credit``
    FK attribute for this subject (``"model"`` or ``"series"``); the
    ContentType, claim set, existing rows and new rows are all derived from
    ``subject_model`` / ``fk_field`` so no concrete subject is named. ``Credit``'s
    model/series XOR constraint guarantees a row belongs to exactly one subject,
    so the two passes never touch each other's rows.
    """
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(subject_model)
    fk_id = f"{fk_field}_id"

    valid_person_pks = set(Person.objects.values_list("pk", flat=True))
    valid_role_pks = set(CreditRole.objects.values_list("pk", flat=True))
    if not valid_role_pks:
        logger.warning(
            "CreditRole table is empty — skipping bulk credit resolution. "
            "Apply the data patches that seed credit roles first."
        )
        return

    credit_qs = Claim.objects.filter(content_type=ct, field_name="credit")
    if subject_ids is not None:
        credit_qs = credit_qs.filter(object_id__in=subject_ids)
    credit_claims = ranked_claims(credit_qs, "object_id", "claim_key")

    winners_by_subject: dict[int, list[Claim]] = {}
    seen: set[ClaimDedupKey] = set()
    for claim in credit_claims:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners_by_subject.setdefault(claim.object_id, []).append(claim)

    desired_by_subject: dict[int, set[CreditAssignment]] = {}
    for subject_id, claims_list in winners_by_subject.items():
        desired: set[CreditAssignment] = set()
        for claim in claims_list:
            val = cast(CreditClaimValue, claim.value)
            if not member_is_present(claim):
                continue
            person_pk = val.get("person")
            if person_pk not in valid_person_pks:
                logger.warning(
                    "Unresolved person pk %r in credit claim (subject pk=%s)",
                    person_pk,
                    subject_id,
                )
                continue
            role_pk = val.get("role")
            if role_pk not in valid_role_pks:
                logger.warning(
                    "Unresolved credit role pk %r in credit claim (subject pk=%s)",
                    role_pk,
                    subject_id,
                )
                continue
            desired.add(CreditAssignment(person_pk, role_pk))
        desired_by_subject[subject_id] = desired

    if subject_ids is not None:
        all_subject_ids = subject_ids
    else:
        all_subject_ids = set(
            subject_model._default_manager.values_list("pk", flat=True)
        )
    existing_by_subject: dict[int, set[CreditAssignment]] = {}
    existing_rows = Credit.objects.filter(**{f"{fk_id}__in": all_subject_ids})
    for subject_id, person_id, role_id in existing_rows.values_list(
        fk_id, "person_id", "role_id"
    ):
        existing_by_subject.setdefault(subject_id, set()).add(
            CreditAssignment(person_id, role_id)
        )

    to_create: list[Credit] = []
    to_delete_pks: list[int] = []

    for subject_id in all_subject_ids:
        desired = desired_by_subject.get(subject_id, set())
        existing = existing_by_subject.get(subject_id, set())

        for assignment in desired - existing:
            to_create.append(
                Credit(
                    **{fk_id: subject_id},
                    person_id=assignment.person_id,
                    role_id=assignment.role_id,
                )
            )

    for pk, subject_id, person_id, role_id in Credit.objects.filter(
        **{f"{fk_id}__in": all_subject_ids}
    ).values_list("pk", fk_id, "person_id", "role_id"):
        desired = desired_by_subject.get(subject_id, set())
        if CreditAssignment(person_id, role_id) not in desired:
            to_delete_pks.append(pk)

    if to_delete_pks:
        Credit.objects.filter(pk__in=to_delete_pks).delete()
    if to_create:
        Credit.objects.bulk_create(to_create, batch_size=2000)


# ------------------------------------------------------------------
# Abbreviation resolvers (string values, dedup logic — not generic M2M)
# ------------------------------------------------------------------


def resolve_all_title_abbreviations(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Bulk-resolve abbreviation claims into TitleAbbreviation rows."""
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(Title)

    abbr_qs = Claim.objects.filter(content_type=ct, field_name="abbreviation")
    if subject_ids is not None:
        abbr_qs = abbr_qs.filter(object_id__in=subject_ids)
    abbr_claims = ranked_claims(abbr_qs, "object_id", "claim_key")

    winners_by_title: dict[int, list[Claim]] = {}
    seen: set[ClaimDedupKey] = set()
    for claim in abbr_claims:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners_by_title.setdefault(claim.object_id, []).append(claim)

    desired_by_title: dict[int, set[str]] = {}
    for title_id, claims_list in winners_by_title.items():
        desired: set[str] = set()
        for claim in claims_list:
            val = cast(AbbreviationClaimValue, claim.value)
            if not member_is_present(claim):
                continue
            desired.add(val["value"])
        desired_by_title[title_id] = desired

    all_title_ids = (
        subject_ids
        if subject_ids is not None
        else set(Title.objects.values_list("pk", flat=True))
    )
    existing_by_title: dict[int, set[str]] = {}
    for title_id, value in TitleAbbreviation.objects.filter(
        title_id__in=all_title_ids
    ).values_list("title_id", "value"):
        existing_by_title.setdefault(title_id, set()).add(value)

    to_create = []
    to_delete_pks: list[int] = []

    for title_id in all_title_ids:
        desired = desired_by_title.get(title_id, set())
        existing = existing_by_title.get(title_id, set())

        for value in desired - existing:
            to_create.append(TitleAbbreviation(title_id=title_id, value=value))

    for pk, title_id, value in TitleAbbreviation.objects.filter(
        title_id__in=all_title_ids
    ).values_list("pk", "title_id", "value"):
        desired = desired_by_title.get(title_id, set())
        if value not in desired:
            to_delete_pks.append(pk)

    if to_delete_pks:
        TitleAbbreviation.objects.filter(pk__in=to_delete_pks).delete()
    if to_create:
        TitleAbbreviation.objects.bulk_create(to_create, batch_size=2000)


def resolve_all_model_abbreviations(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Bulk-resolve abbreviation claims into ModelAbbreviation rows."""
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(MachineModel)

    abbr_qs = Claim.objects.filter(content_type=ct, field_name="abbreviation")
    if subject_ids is not None:
        abbr_qs = abbr_qs.filter(object_id__in=subject_ids)
    abbr_claims = ranked_claims(abbr_qs, "object_id", "claim_key")

    winners_by_model: dict[int, list[Claim]] = {}
    seen: set[ClaimDedupKey] = set()
    for claim in abbr_claims:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners_by_model.setdefault(claim.object_id, []).append(claim)

    desired_by_model: dict[int, set[str]] = {}
    for model_id, claims_list in winners_by_model.items():
        desired: set[str] = set()
        for claim in claims_list:
            val = cast(AbbreviationClaimValue, claim.value)
            if not member_is_present(claim):
                continue
            desired.add(val["value"])
        desired_by_model[model_id] = desired

    all_model_ids = (
        subject_ids
        if subject_ids is not None
        else set(MachineModel.objects.values_list("pk", flat=True))
    )

    # Claim-local: the model's own winning abbreviations are materialized as-is,
    # including any that also belong to its Title. The Title dedup is a read-time
    # view (api.helpers.displayed_model_abbreviations), not a write-time
    # subtraction — see docs/plans/provenance/ClaimResolutionRefactor.md.
    existing_by_model: dict[int, set[str]] = {}
    for model_id, value in ModelAbbreviation.objects.filter(
        machine_model_id__in=all_model_ids
    ).values_list("machine_model_id", "value"):
        existing_by_model.setdefault(model_id, set()).add(value)

    to_create = []
    to_delete_pks: list[int] = []

    for model_id in all_model_ids:
        desired = desired_by_model.get(model_id, set())
        existing = existing_by_model.get(model_id, set())

        for value in desired - existing:
            to_create.append(ModelAbbreviation(machine_model_id=model_id, value=value))

    for pk, model_id, value in ModelAbbreviation.objects.filter(
        machine_model_id__in=all_model_ids
    ).values_list("pk", "machine_model_id", "value"):
        desired = desired_by_model.get(model_id, set())
        if value not in desired:
            to_delete_pks.append(pk)

    if to_delete_pks:
        ModelAbbreviation.objects.filter(pk__in=to_delete_pks).delete()
    if to_create:
        ModelAbbreviation.objects.bulk_create(to_create, batch_size=2000)


# ------------------------------------------------------------------
# Alias resolvers (all five alias types)
# ------------------------------------------------------------------


def _get_parents_through(parent: type[ClaimControlledModel]) -> type[Model]:
    """Return the through model for ``parent``'s self-referential ``parents`` M2M.

    ``parent.parents.through`` is a runtime-generated descriptor django-stubs can't
    see.  Confining the ignore to this helper keeps the category-3 ``Any`` leak out of
    ``_resolve_parents``.
    """
    through: type[Model] = parent.parents.through  # type: ignore[attr-defined]
    return through


def _resolve_aliases(parent_model: type[ClaimControlledModel]) -> None:
    """Bulk-resolve a parent entity's alias claims into its alias model rows.

    Everything about the alias type — claim field, alias model, FK column — comes from
    the canonical alias registry, so callers supply only the parent model.

    Reads the parent's alias claims, diffs against current alias rows, creates missing
    rows, updates display-case changes, and deletes stale rows. Claims store lowercase
    alias_value (for key stability) and an optional alias_display (original case) for
    user-facing display.
    """
    from django.contrib.contenttypes.models import ContentType

    at = alias_type_for(parent_model)
    assert at is not None, f"{parent_model.__name__} is not a registered alias type"
    alias_model = at.alias_model
    fk_col = at.fk_name + "_id"
    claim_field = at.claim_field

    ct = ContentType.objects.get_for_model(parent_model)

    claims_qs = ranked_claims(
        Claim.objects.filter(content_type=ct, field_name=claim_field),
        "object_id",
        "claim_key",
    )

    # Pick winners per (object_id, claim_key).
    winners_by_parent: dict[int, list[Claim]] = {}
    seen: set[ClaimDedupKey] = set()
    for claim in claims_qs:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners_by_parent.setdefault(claim.object_id, []).append(claim)

    # Build desired aliases per parent: {lower_val → display_val}.
    # alias_display (original case) is preferred via the schema's
    # display_key declaration; falls back to alias_value when absent/empty.
    schema = get_relationship_schema(claim_field)
    assert schema is not None, (
        f"alias namespace {claim_field!r} has no registered relationship schema"
    )
    desired_by_parent: dict[int, dict[str, str]] = {}
    for parent_id, claims_list in winners_by_parent.items():
        desired: dict[str, str] = {}
        for claim in claims_list:
            val = cast(AliasClaimValue, claim.value)
            if not member_is_present(claim):
                continue
            alias_val = val.get("alias_value", "")
            if alias_val:
                override = get_display_override(val, schema, "alias_value")
                # Schema registration pins ``alias_display.scalar_type`` to
                # ``str``, so the override (when present) is always a str at
                # runtime. ``str(...)`` keeps mypy happy without coercing.
                display = str(override) if override is not None else alias_val
                desired[alias_val] = display  # alias_val is already lowercase
        desired_by_parent[parent_id] = desired

    # Pre-fetch existing alias rows, keyed by lowercase value: {lower → (pk, stored_value)}.
    all_parent_ids = set(parent_model._default_manager.values_list("pk", flat=True))
    existing_by_parent: dict[int, dict[str, tuple[int, str]]] = {}
    for row in alias_model._default_manager.values_list("pk", fk_col, "value"):
        pk_val, parent_id, value = row
        existing_by_parent.setdefault(parent_id, {})[value.lower()] = (pk_val, value)

    to_create = []
    to_delete_pks: list[int] = []
    to_update: list[tuple[int, str]] = []  # (pk, new_display_value)

    for parent_id in all_parent_ids:
        desired = desired_by_parent.get(parent_id, {})
        existing = existing_by_parent.get(parent_id, {})

        for lower_val, display_val in desired.items():
            if lower_val not in existing:
                to_create.append(
                    alias_model(**{fk_col: parent_id, "value": display_val})
                )
            else:
                existing_pk, stored_val = existing[lower_val]
                if stored_val != display_val:
                    to_update.append((existing_pk, display_val))

        for lower_val, (alias_pk, _) in existing.items():
            if lower_val not in desired:
                to_delete_pks.append(alias_pk)

    if to_delete_pks:
        alias_model._default_manager.filter(pk__in=to_delete_pks).delete()
    if to_create:
        alias_model._default_manager.bulk_create(
            to_create, batch_size=2000, ignore_conflicts=True
        )
    for pk, display_val in to_update:
        alias_model._default_manager.filter(pk=pk).update(value=display_val)


# ---------------------------------------------------------------------------
# Alias registry — drives resolve_all_aliases() and dispatch
# ---------------------------------------------------------------------------
# No import-time snapshot of the engine alias registry: this module is imported
# *during* ``CatalogConfig.ready`` (via ``register_catalog_resolve_handlers``),
# which is before ``register_alias_types`` has populated the registry, so a
# module-level ``list(discover_alias_types())`` would freeze an empty result.
# Every consumer reads the live registry via ``discover_alias_types()`` instead
# (see ``resolve_all_aliases`` below; the alias test suite parametrizes over it).


def resolve_theme_aliases() -> None:
    _resolve_aliases(Theme)


def resolve_manufacturer_aliases() -> None:
    _resolve_aliases(Manufacturer)


def resolve_person_aliases() -> None:
    _resolve_aliases(Person)


def resolve_gameplay_feature_aliases() -> None:
    _resolve_aliases(GameplayFeature)


def resolve_reward_type_aliases() -> None:
    _resolve_aliases(RewardType)


def resolve_corporate_entity_aliases() -> None:
    _resolve_aliases(CorporateEntity)


def resolve_all_aliases() -> None:
    """Resolve all alias types from the auto-discovered registry."""
    for at in discover_alias_types():
        _resolve_aliases(at.parent_model)


# ------------------------------------------------------------------
# Parent hierarchy resolvers (Theme and GameplayFeature DAGs)
# ------------------------------------------------------------------


def _resolve_parents(
    parent_model: type[ClaimControlledModel], *, claim_field_prefix: str | None = None
) -> None:
    """Resolve parent hierarchy claims into self-referential M2M rows.

    Reads {claim_field_prefix}_parent claims on parent_model instances.
    Each claim value contains {"parent": pk}.
    Materializes the self-referential parents M2M.

    *claim_field_prefix* defaults to model_name but must be overridden when
    the model name differs from the claim field convention (e.g.
    ``gameplayfeature`` vs ``gameplay_feature``).
    """
    from django.contrib.contenttypes.models import ContentType

    model_name = parent_model._meta.model_name
    prefix = claim_field_prefix or model_name
    claim_field_name = f"{prefix}_parent"
    ct = ContentType.objects.get_for_model(parent_model)

    claims_qs = ranked_claims(
        Claim.objects.filter(content_type=ct, field_name=claim_field_name),
        "object_id",
        "claim_key",
    )

    # Pick winners per (object_id, claim_key).
    winners_by_child: dict[int, list[Claim]] = {}
    seen: set[ClaimDedupKey] = set()
    for claim in claims_qs:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key not in seen:
            seen.add(key)
            winners_by_child.setdefault(claim.object_id, []).append(claim)

    valid_pks = set(parent_model.objects.values_list("pk", flat=True))  # type: ignore[attr-defined]

    desired_by_child: dict[int, set[int]] = {}
    for child_id, claims_list in winners_by_child.items():
        desired: set[int] = set()
        for claim in claims_list:
            val = cast(ParentClaimValue, claim.value)
            if not member_is_present(claim):
                continue
            parent_pk = val.get("parent")
            if parent_pk not in valid_pks:
                logger.warning(
                    "Unresolved %s parent pk %r for pk=%s",
                    claim_field_name,
                    parent_pk,
                    child_id,
                )
                continue
            desired.add(parent_pk)
        desired_by_child[child_id] = desired

    # Self-referential M2M through-table columns are from_{model}_id / to_{model}_id.
    through = _get_parents_through(parent_model)
    from_col = f"from_{model_name}_id"
    to_col = f"to_{model_name}_id"

    all_child_ids = set(parent_model.objects.values_list("pk", flat=True))  # type: ignore[attr-defined]
    existing_by_child: dict[int, set[int]] = {}
    for row in through._default_manager.filter(
        **{f"{from_col}__in": all_child_ids}
    ).values_list(from_col, to_col):
        existing_by_child.setdefault(row[0], set()).add(row[1])

    to_create = []
    to_delete_pks: list[int] = []

    for child_id in all_child_ids:
        desired = desired_by_child.get(child_id, set())
        existing = existing_by_child.get(child_id, set())

        for parent_pk in desired - existing:
            to_create.append(through(**{from_col: child_id, to_col: parent_pk}))

    for row in through._default_manager.filter(
        **{f"{from_col}__in": all_child_ids}
    ).values_list("pk", from_col, to_col):
        pk, child_id, parent_pk = row
        desired = desired_by_child.get(child_id, set())
        if parent_pk not in desired:
            to_delete_pks.append(pk)

    if to_delete_pks:
        through._default_manager.filter(pk__in=to_delete_pks).delete()
    if to_create:
        through._default_manager.bulk_create(
            to_create, batch_size=2000, ignore_conflicts=True
        )


def resolve_theme_parents() -> None:
    _resolve_parents(Theme)


def resolve_gameplay_feature_parents() -> None:
    _resolve_parents(GameplayFeature, claim_field_prefix="gameplay_feature")


# ------------------------------------------------------------------
# Location alias resolver
# ------------------------------------------------------------------


def resolve_all_location_aliases() -> None:
    """Resolve location_alias claims into LocationAlias rows."""
    _resolve_aliases(Location)


# ------------------------------------------------------------------
# CorporateEntityLocation resolver
# ------------------------------------------------------------------


def resolve_all_corporate_entity_locations(
    *,
    subject_ids: set[int] | None = None,
) -> None:
    """Sync CorporateEntityLocation rows from active 'location' claims on CorporateEntity.

    When *subject_ids* is ``None`` (the default), processes ALL CorporateEntity
    rows so that CEs whose claims were all deactivated also have their stale
    rows removed.  When scoped to a set of entity PKs, only those CEs are
    considered.
    """
    from collections import defaultdict

    from django.contrib.contenttypes.models import ContentType

    ce_ct = ContentType.objects.get_for_model(CorporateEntity)
    valid_loc_pks = set(Location.objects.values_list("pk", flat=True))

    claims_qs = Claim.objects.filter(content_type=ce_ct, field_name="location")
    if subject_ids is not None:
        claims_qs = claims_qs.filter(object_id__in=subject_ids)
    claims = ranked_claims(claims_qs, "object_id", "claim_key")

    # Pick the winning claim per (object_id, claim_key) by source priority, then
    # keep only the present locations.  Uniform with the sibling resolvers: a
    # higher-priority exists=False retraction wins over a lower-priority assertion.
    desired: dict[int, set[int]] = defaultdict(set)
    seen: set[ClaimDedupKey] = set()
    for claim in claims:
        key = ClaimDedupKey(claim.object_id, claim.claim_key)
        if key in seen:
            continue
        seen.add(key)
        val = cast(LocationClaimValue, claim.value or {})
        if not member_is_present(claim):
            continue
        loc_pk = val.get("location")
        if loc_pk and loc_pk in valid_loc_pks:
            desired[claim.object_id].add(loc_pk)

    existing_qs = CorporateEntityLocation.objects.all()
    if subject_ids is not None:
        existing_qs = existing_qs.filter(corporate_entity_id__in=subject_ids)

    current: dict[int, dict[int, CorporateEntityLocation]] = defaultdict(dict)
    for cel in existing_qs:
        location_id = cel.location_id
        current[cel.corporate_entity_id][location_id] = cel

    # Create missing rows.
    for ce_pk, loc_pks in desired.items():
        for loc_pk in loc_pks:
            if loc_pk not in current[ce_pk]:
                CorporateEntityLocation.objects.create(
                    corporate_entity_id=ce_pk,
                    location_id=loc_pk,
                )

    # Delete stale rows (location no longer desired, or CE lost all claims).
    stale_pks: list[int] = []
    for ce_pk, loc_map in current.items():
        wanted = desired.get(ce_pk, set())
        for loc_pk, cel in loc_map.items():
            if loc_pk not in wanted:
                stale_pks.append(cel.pk)
    if stale_pks:
        CorporateEntityLocation.objects.filter(pk__in=stale_pks).delete()
