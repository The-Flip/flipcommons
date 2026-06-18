"""Domain spec-builders for PATCH claims endpoints.

The per-relationship planners that know concrete catalog shapes (credits,
gameplay features, M2Ms, abbreviations, parents, aliases). Each validates
domain input and returns a list of :class:`ClaimSpec` for the generic write
engine in :mod:`.claim_write` to execute.

These import from :mod:`.claim_write`, never the reverse: the domain layer
depends on the generic engine, not vice versa.
"""

from __future__ import annotations

from apps.catalog.models import (
    CorporateEntity,
    CreditRole,
    GameplayFeature,
    Location,
    MachineModel,
    Person,
    Theme,
    Title,
)
from apps.core.models import SluggedModel
from apps.provenance.claims import (
    build_relationship_claim,
    normalize_abbreviation_value,
    normalize_alias_identity,
)
from apps.provenance.validation import get_relationship_schema

from ._typing import CreditKey, CreditPkKey
from .claim_write import ClaimSpec, ValidationErrors, raise_form_error
from .schemas import CreditInputSchema, GameplayFeatureInputSchema

# Concrete catalog models with a self-referencing ``parents`` M2M / reverse
# ``aliases`` relation, typed as unions rather than a structural protocol
# because the two helpers are only called from a handful of sites.
_ParentEntity = GameplayFeature | Theme
_AliasEntity = GameplayFeature | Theme | CorporateEntity | Location


def plan_parent_claims(
    entity: _ParentEntity,
    desired_slugs: set[str],
    *,
    model_class: type[_ParentEntity],
    claim_field_name: str,
) -> list[ClaimSpec]:
    """Validate parent hierarchy changes and return diff-based ClaimSpecs.

    Works for any model with a self-referencing ``parents`` M2M resolved
    via relationship claims (GameplayFeature, Theme).

    Raises HttpError 422 on invalid slugs, self-links, or cycles.
    """
    if entity.slug in desired_slugs:
        raise_form_error(f"A {model_class.__name__} cannot be its own parent.")

    # Resolve desired slugs → PKs (also validates existence).
    slug_to_pk = dict(
        model_class._default_manager.filter(slug__in=desired_slugs).values_list(
            "slug", "pk"
        )
    )
    missing = desired_slugs - slug_to_pk.keys()
    if missing:
        raise_form_error(f"Unknown parent slugs: {sorted(missing)}")

    # Cycle detection: for each proposed parent, walk up the existing
    # graph (excluding the edited entity's current parents, since
    # they're being replaced). If we reach the edited entity, reject.
    if desired_slugs:
        all_entities = model_class._default_manager.prefetch_related("parents").all()
        parent_map: dict[str, set[str]] = {}
        for e in all_entities:
            if e.slug == entity.slug:
                continue
            parent_map[e.slug] = {p.slug for p in e.parents.all()}

        for start_slug in desired_slugs:
            visited: set[str] = set()
            stack = [start_slug]
            while stack:
                current = stack.pop()
                if current == entity.slug:
                    raise_form_error(
                        f"Adding parent '{start_slug}' would create a cycle.",
                    )
                if current in visited:
                    continue
                visited.add(current)
                stack.extend(parent_map.get(current, set()))

    # Diff against current M2M state (by PK).
    desired_pks = set(slug_to_pk.values())
    current_pks = set(entity.parents.values_list("pk", flat=True))
    specs: list[ClaimSpec] = []
    for parent_pk in desired_pks - current_pks:
        claim_key, value = build_relationship_claim(
            claim_field_name, {"parent": parent_pk}
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    for parent_pk in current_pks - desired_pks:
        claim_key, value = build_relationship_claim(
            claim_field_name, {"parent": parent_pk}, exists=False
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    return specs


def plan_alias_claims(
    entity: _AliasEntity,
    desired_aliases: list[str],
    *,
    claim_field_name: str,
) -> list[ClaimSpec]:
    """Validate alias changes and return diff-based ClaimSpecs.

    Normalises input (strip, deduplicate by lowercase key) and diffs
    against current alias rows.  Preserves user-typed case via
    ``alias_display`` so the resolver stores the display form.

    Returns specs for adds, removes, and display-case updates.
    """
    # Normalise: strip, deduplicate by lowercase key, drop blanks.
    # Last-write-wins for display case when duplicates differ only in case.
    # The strip/lower fold is shared with the data-patch adapter via
    # ``normalize_alias_identity`` so the two paths produce identical bytes.
    desired: dict[str, str] = {}  # lowercase → display string
    for raw in desired_aliases:
        ident = normalize_alias_identity(raw)
        if ident.value:
            desired[ident.value] = ident.display

    current: dict[str, str] = {}  # lowercase → stored display string
    for a in entity.aliases.all():
        current[a.value.lower()] = a.value

    specs: list[ClaimSpec] = []
    # Adds and display-case updates
    for lower, display in desired.items():
        if lower not in current or current[lower] != display:
            claim_key, value = build_relationship_claim(
                claim_field_name,
                {"alias_value": lower, "alias_display": display},
            )
            specs.append(
                ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
            )
    # Removes
    for lower in current.keys() - desired.keys():
        claim_key, value = build_relationship_claim(
            claim_field_name, {"alias_value": lower}, exists=False
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    return specs


def plan_m2m_claims(
    entity: MachineModel,
    desired_slugs: set[str],
    *,
    target_model: type[SluggedModel],
    claim_field_name: str,
    m2m_attr: str,
) -> list[ClaimSpec]:
    """Validate and diff a simple slug-set M2M relationship.

    Works for any MachineModel M2M that is resolved by PK (themes, tags,
    reward_types).  The API receives slugs; this function resolves them to
    PKs before building claims.  Unlike ``plan_parent_claims``, no hierarchy
    or cycle checks are needed.

    Raises HttpError 422 on unknown slugs.
    """
    if desired_slugs:
        slug_to_pk = dict(
            target_model._default_manager.filter(slug__in=desired_slugs).values_list(
                "slug", "pk"
            )
        )
        missing = desired_slugs - slug_to_pk.keys()
        if missing:
            raise_form_error(f"Unknown {claim_field_name} slugs: {sorted(missing)}")
        desired_pks = set(slug_to_pk.values())
    else:
        desired_pks = set()

    current_pks = set(getattr(entity, m2m_attr).values_list("pk", flat=True))
    return build_m2m_claim_specs(
        current=current_pks,
        desired=desired_pks,
        claim_field_name=claim_field_name,
    )


def build_m2m_claim_specs(
    *,
    current: set[int],
    desired: set[int],
    claim_field_name: str,
) -> list[ClaimSpec]:
    """Build diff-based ClaimSpecs for simple PK-set M2M relationships."""
    specs: list[ClaimSpec] = []
    for pk in desired - current:
        claim_key, value = build_relationship_claim(
            claim_field_name, {claim_field_name: pk}
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    for pk in current - desired:
        claim_key, value = build_relationship_claim(
            claim_field_name, {claim_field_name: pk}, exists=False
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    return specs


def normalize_gameplay_feature_inputs(
    desired_features: list[tuple[str, int | None]],
    *,
    available_slugs: set[str] | None = None,
) -> dict[str, int | None]:
    """Normalize gameplay feature input into a slug->count map.

    Duplicate slugs are rejected. Counts, when provided, must be positive.
    When ``available_slugs`` is provided, unknown slugs are rejected without
    touching the database.

    Field errors are keyed ``gameplay_features.{slug}`` so the frontend can
    display them inline on the corresponding row.
    """
    errors = ValidationErrors()
    desired: dict[str, int | None] = {}
    for slug, count in desired_features:
        if slug in desired:
            errors.add_field(f"gameplay_features.{slug}", "Duplicate feature.")
            continue
        if count is not None and count <= 0:
            errors.add_field(
                f"gameplay_features.{slug}", f"Count must be positive, got {count}."
            )
            continue
        desired[slug] = count

    if available_slugs is not None:
        for slug in set(desired.keys()) - available_slugs:
            errors.add_field(f"gameplay_features.{slug}", "Unknown gameplay feature.")

    errors.raise_if_errors()
    return desired


def build_gameplay_feature_claim_specs(
    current: dict[int, int | None],
    desired: dict[int, int | None],
) -> list[ClaimSpec]:
    """Build diff-based ClaimSpecs for gameplay feature relationship changes."""
    specs: list[ClaimSpec] = []
    for pk, count in desired.items():
        if pk not in current or current[pk] != count:
            claim_key, value = build_relationship_claim(
                "gameplay_feature", {"gameplay_feature": pk}
            )
            value["count"] = count
            specs.append(
                ClaimSpec(
                    field_name="gameplay_feature",
                    value=value,
                    claim_key=claim_key,
                )
            )
    for pk in current.keys() - desired.keys():
        claim_key, value = build_relationship_claim(
            "gameplay_feature", {"gameplay_feature": pk}, exists=False
        )
        specs.append(
            ClaimSpec(
                field_name="gameplay_feature",
                value=value,
                claim_key=claim_key,
            )
        )
    return specs


def plan_gameplay_feature_claims(
    entity: MachineModel,
    desired_features: list[GameplayFeatureInputSchema],
) -> list[ClaimSpec]:
    """Validate and diff gameplay features (slug + optional count) on a MachineModel.

    Each entry has a ``slug`` and optional ``count``.  Duplicate slugs in the
    input are rejected.  Count must be positive if provided.

    Assumes ``entity`` has a ``machinemodelgameplayfeature_set`` reverse
    relation (i.e., is a MachineModel with that through-table prefetched).

    Raises HttpError 422 on invalid input.
    """
    raw_desired = [(feat.slug, feat.count) for feat in desired_features]
    if raw_desired:
        existing = set(
            GameplayFeature.objects.filter(
                slug__in={slug for slug, _ in raw_desired}
            ).values_list("slug", flat=True)
        )
        desired = normalize_gameplay_feature_inputs(
            raw_desired, available_slugs=existing
        )
    else:
        desired = normalize_gameplay_feature_inputs(raw_desired)

    # Resolve slugs → PKs.
    slug_to_pk = dict(
        GameplayFeature.objects.filter(slug__in=desired.keys()).values_list(
            "slug", "pk"
        )
    )
    desired_by_pk: dict[int, int | None] = {
        slug_to_pk[slug]: count for slug, count in desired.items()
    }

    # Current state from prefetched through-table (by PK).
    current_by_pk: dict[int, int | None] = {}
    for row in entity.machinemodelgameplayfeature_set.all():
        current_by_pk[row.gameplayfeature_id] = row.count

    return build_gameplay_feature_claim_specs(current_by_pk, desired_by_pk)


def plan_abbreviation_claims(
    entity: MachineModel | Title,
    desired_values: list[str],
) -> list[ClaimSpec]:
    """Validate and diff abbreviation changes.

    Normalises input (strip, deduplicate, drop blanks, enforce max length)
    and diffs against current abbreviation rows.

    Shared by MachineModel and Title.
    """
    desired = set(_normalize_abbreviations(desired_values))
    current = set(entity.abbreviations.values_list("value", flat=True))
    specs: list[ClaimSpec] = []

    for value in desired - current:
        claim_key, claim_value = build_relationship_claim(
            "abbreviation", {"value": value}
        )
        specs.append(
            ClaimSpec(field_name="abbreviation", value=claim_value, claim_key=claim_key)
        )

    for value in current - desired:
        claim_key, claim_value = build_relationship_claim(
            "abbreviation", {"value": value}, exists=False
        )
        specs.append(
            ClaimSpec(field_name="abbreviation", value=claim_value, claim_key=claim_key)
        )
    return specs


def plan_credit_claims(
    entity: MachineModel,
    desired_credits: list[CreditInputSchema],
) -> list[ClaimSpec]:
    """Validate and diff credits (person_slug + role) on a MachineModel.

    Each entry has a ``person_slug`` and ``role`` (role slug).  Duplicate
    (person_slug, role) pairs in the input are rejected.

    Assumes ``entity`` has ``credits`` prefetched with
    select_related("person", "role").

    Raises HttpError 422 on invalid input.
    """
    raw_desired = [
        CreditKey(credit.person_slug, credit.role) for credit in desired_credits
    ]

    if raw_desired:
        desired_person_slugs = {p for p, _ in raw_desired}
        existing_people = set(
            Person.objects.filter(slug__in=desired_person_slugs).values_list(
                "slug", flat=True
            )
        )
        desired_role_slugs = {r for _, r in raw_desired}
        existing_roles = set(
            CreditRole.objects.filter(slug__in=desired_role_slugs).values_list(
                "slug", flat=True
            )
        )
        desired = normalize_credit_inputs(
            raw_desired,
            available_people=existing_people,
            available_roles=existing_roles,
        )
    else:
        desired = normalize_credit_inputs(raw_desired)

    # Resolve slugs → PKs for claim building.
    if desired:
        person_slug_to_pk = dict(
            Person.objects.filter(slug__in={p for p, _ in desired}).values_list(
                "slug", "pk"
            )
        )
        role_slug_to_pk = dict(
            CreditRole.objects.filter(slug__in={r for _, r in desired}).values_list(
                "slug", "pk"
            )
        )
        desired_pks: set[CreditPkKey] = {
            CreditPkKey(person_slug_to_pk[p], role_slug_to_pk[r]) for p, r in desired
        }
    else:
        desired_pks = set()

    # Current state from prefetched credits (by PK).
    current_pks: set[CreditPkKey] = set()
    for credit in entity.credits.all():
        current_pks.add(CreditPkKey(credit.person_id, credit.role_id))

    return build_credit_claim_specs(current_pks, desired_pks)


def normalize_credit_inputs(
    desired_credits: list[CreditKey],
    *,
    available_people: set[str] | None = None,
    available_roles: set[str] | None = None,
) -> set[CreditKey]:
    """Normalize credits into unique (person_slug, role_slug) pairs.

    When available slug sets are provided, unknown people or roles are rejected
    without touching the database.

    Field errors are keyed ``credits.{person_slug}:{role}`` so the frontend
    can display them inline on the corresponding row.
    """
    errors = ValidationErrors()
    desired: set[CreditKey] = set()
    for person_slug, role in desired_credits:
        pair = CreditKey(person_slug, role)
        if pair in desired:
            errors.add_field(f"credits.{person_slug}:{role}", "Duplicate credit.")
            continue
        desired.add(pair)

    if available_people is not None:
        missing_people = {p for p, _ in desired} - available_people
        if missing_people:
            for person_slug, role in desired:
                if person_slug in missing_people:
                    errors.add_field(
                        f"credits.{person_slug}:{role}",
                        f"Unknown person: {person_slug}.",
                    )

    if available_roles is not None:
        missing_roles = {r for _, r in desired} - available_roles
        if missing_roles:
            for person_slug, role in desired:
                if role in missing_roles:
                    errors.add_field(
                        f"credits.{person_slug}:{role}",
                        f"Unknown role: {role}.",
                    )

    errors.raise_if_errors()
    return desired


def build_credit_claim_specs(
    current: set[CreditPkKey],
    desired: set[CreditPkKey],
) -> list[ClaimSpec]:
    """Build diff-based ClaimSpecs for credit relationship changes."""
    specs: list[ClaimSpec] = []
    for person_pk, role_pk in desired - current:
        claim_key, value = build_relationship_claim(
            "credit", {"person": person_pk, "role": role_pk}
        )
        specs.append(ClaimSpec(field_name="credit", value=value, claim_key=claim_key))
    for person_pk, role_pk in current - desired:
        claim_key, value = build_relationship_claim(
            "credit", {"person": person_pk, "role": role_pk}, exists=False
        )
        specs.append(ClaimSpec(field_name="credit", value=value, claim_key=claim_key))
    return specs


def _abbreviation_max_length() -> int:
    """The abbreviation length bound, read from the registered schema.

    Model-derived (populated from the through-model ``CharField`` at
    registration), so the editor and the data-patch adapter enforce the same
    limit from one source instead of a hardcoded constant.
    """
    schema = get_relationship_schema("abbreviation")
    assert schema is not None, "abbreviation schema must be registered"
    (spec,) = [s for s in schema.value_keys if s.identity is not None]
    assert spec.max_length is not None, "abbreviation identity must declare max_length"
    return spec.max_length


def _normalize_abbreviations(values: list[str]) -> list[str]:
    """Strip, deduplicate, drop blanks, enforce max length.

    The strip fold is shared with the data-patch adapter via
    ``normalize_abbreviation_value`` and the length bound comes from the
    registered schema (``_abbreviation_max_length``), so both write paths
    normalize and bound identically.
    """
    max_length = _abbreviation_max_length()
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = normalize_abbreviation_value(raw_value)
        if not value:
            continue
        if len(value) > max_length:
            raise_form_error(f"Abbreviations must be {max_length} characters or fewer.")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized
