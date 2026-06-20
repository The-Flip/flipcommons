"""Claim resolution logic.

Given a catalog entity, fetch all active claims, pick the winner per
claim_key (highest source priority, most recent if tied), and write back
the resolved values.

Each dimension has its own merge policy, in CRDT register/set terms: scalar, FK
and ``status`` are **last-writer-wins registers** (one winner per claim_key);
relationship membership is a **set** with **per-element last-writer-wins** (each
member independently winner-picked, an ``exists=false`` tombstone able to win and
remove it) — *not* add-wins, so never union members instead of ranking them. The
materialized columns are a view over the claim log; anything that needs a
resolved value reuses these primitives (``ranked_claims``, ``member_is_present``,
``is_live``) and matches this path — never reimplements the merge, since a second
implementation is where a derived value drifts from what apply produces.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import OutputWrapper
from django.utils import timezone

from apps.core.types import JsonBody
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.licensing import (
    SourceFieldLicenseMap,
    build_source_field_license_map,
    resolve_effective_license,
)
from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.validation import get_relationship_namespaces

from ..models import (
    MachineModel,
    Title,
)
from ._dispatch import register_catalog_resolve_handlers
from ._entities import (
    _resolve_bulk,
    _resolve_single,
    resolve_all_entities,
    resolve_entity,
)
from ._helpers import (
    FKInfo,
    _coerce,
    _resolve_fk_generic,
    build_fk_info,
    get_field_defaults,
    get_preserve_fields,
    resolve_unique_conflicts,
    validate_check_constraints,
)
from ._media import resolve_media_attachments
from ._relationships import (
    resolve_all_aliases,
    resolve_all_corporate_entity_locations,
    resolve_all_credits,
    resolve_all_gameplay_features,
    resolve_all_location_aliases,
    resolve_all_model_abbreviations,
    resolve_all_reward_types,
    resolve_all_series_credits,
    resolve_all_tags,
    resolve_all_themes,
    resolve_all_title_abbreviations,
    resolve_corporate_entity_aliases,
    resolve_gameplay_feature_aliases,
    resolve_gameplay_feature_parents,
    resolve_manufacturer_aliases,
    resolve_person_aliases,
    resolve_reward_type_aliases,
    resolve_theme_aliases,
    resolve_theme_parents,
)

logger = logging.getLogger(__name__)

# Claim field_names whose values are images. License metadata for these
# fields gets denormalized into extra_data so the API can filter by
# permissiveness_rank without joining back through claims.
IMAGE_FIELDS = frozenset({"opdb.images", "ipdb.image_urls", "image_urls"})


def resolve_model(machine_model: MachineModel) -> MachineModel:
    """Resolve all active claims into the given MachineModel's fields.

    Picks the winning claim per claim_key: highest effective priority
    (from source or user profile), then most recent created_at as tiebreaker.
    Delegates field application to ``_apply_resolution()`` (shared with the
    bulk path in ``resolve_machine_models()``).

    Returns the saved MachineModel.
    """
    # Fetch and pick winners (single-object).
    claims = ranked_claims(machine_model.claims.all(), "claim_key").select_related(
        "source__default_license"
    )
    winners: dict[str, Claim] = {}
    for claim in claims:
        if claim.claim_key not in winners:
            winners[claim.claim_key] = claim

    # Apply field values (shared with bulk path).
    from apps.provenance.models import get_claim_fields

    claim_fields = get_claim_fields(MachineModel)
    field_defaults = get_field_defaults(MachineModel, claim_fields)
    fk_info = build_fk_info(MachineModel, claim_fields)
    sfl_map = build_source_field_license_map()
    preserve_when_unclaimed = get_preserve_fields(MachineModel, claim_fields)
    original_slug = machine_model.slug
    original_opdb_id = machine_model.opdb_id
    _apply_resolution(
        machine_model,
        winners,
        claim_fields,
        field_defaults,
        fk_info,
        sfl_map,
        preserve_when_unclaimed,
    )

    # Post-resolution guards for cross-reference fields only (slug, opdb_id).
    # Other unique fields (e.g. name) rely on save() → IntegrityError which
    # execute_claims() catches and returns as 422.
    conflict_fields = [
        ("slug", original_slug, original_slug),  # (attr, check_original, revert_to)
        ("opdb_id", original_opdb_id, None),  # nullable — clear to None
    ]
    for attr, original, revert in conflict_fields:
        value = getattr(machine_model, attr)
        if not value or value == original:
            continue
        conflict = (
            MachineModel.objects.filter(**{attr: value})
            .exclude(pk=machine_model.pk)
            .first()
        )
        if conflict:
            logger.warning(
                "Cannot resolve %s=%r onto '%s' (pk=%s): already owned by '%s' (pk=%s)",
                attr,
                value,
                machine_model.name,
                machine_model.pk,
                conflict.name,
                conflict.pk,
            )
            setattr(machine_model, attr, revert)

    validate_check_constraints(machine_model)
    machine_model.save()

    # Resolve relationship claims after scalar save.
    subject_ids = {machine_model.pk}
    resolve_all_credits(subject_ids=subject_ids)
    resolve_all_themes(subject_ids=subject_ids)
    resolve_all_gameplay_features(subject_ids=subject_ids)
    resolve_all_reward_types(subject_ids=subject_ids)
    resolve_all_tags(subject_ids=subject_ids)
    resolve_all_model_abbreviations(subject_ids=subject_ids)

    from django.contrib.contenttypes.models import ContentType

    ct_mm = ContentType.objects.get_for_model(MachineModel)
    resolve_media_attachments(content_type_id=ct_mm.id, subject_ids=subject_ids)

    return machine_model


def resolve_machine_models(stdout: OutputWrapper | None = None) -> int:
    """Re-resolve every MachineModel and its dependencies from claims (bulk-optimized).

    Resolves in dependency order: locations → taxonomy → titles → machine models
    + their relationships (credits, themes, gameplay features, etc.).
    Does NOT resolve manufacturers, corporate entities, or people.
    Pre-fetches all lookup tables and claims in ~4 queries, resolves
    in memory, then writes back with a single bulk_update().
    """

    def _status(msg: str) -> None:
        if stdout:
            stdout.write(f"  {msg}")

    # 0. Resolve entity scalars in dependency order (FK targets first).
    from ..models import (
        GameplayFeature,
        Location,
        Theme,
    )
    from ..models.taxonomy import (
        Cabinet,
        CreditRole,
        DisplaySubtype,
        DisplayType,
        GameFormat,
        RewardType,
        Tag,
        TechnologyGeneration,
        TechnologySubgeneration,
    )

    resolve_all_entities(Location)
    resolve_all_location_aliases()
    _status("Locations resolved")

    from ..models import Franchise, Series, System

    tax_models: list[type[ClaimControlledModel]] = [
        TechnologyGeneration,
        TechnologySubgeneration,
        DisplayType,
        DisplaySubtype,
        Cabinet,
        GameFormat,
        RewardType,
        Tag,
        CreditRole,
        Franchise,
        Series,
        System,
    ]
    for tax_model in tax_models:
        resolve_all_entities(tax_model)
    resolve_all_entities(Theme)
    resolve_all_entities(GameplayFeature)
    _status("Taxonomy, themes, gameplay features resolved")

    resolve_theme_parents()
    resolve_gameplay_feature_parents()
    resolve_all_aliases()
    _status("Hierarchy and aliases resolved")

    resolve_all_corporate_entity_locations()
    _status("Corporate entity locations resolved")

    resolve_all_entities(Title)
    _status("Titles resolved")

    # 0c. Resolve title abbreviations.
    resolve_all_title_abbreviations()

    # 1. Pre-fetch lookup tables.
    from apps.provenance.models import get_claim_fields

    claim_fields = get_claim_fields(MachineModel)
    field_defaults = get_field_defaults(MachineModel, claim_fields)
    fk_info = build_fk_info(MachineModel, claim_fields)
    sfl_map = build_source_field_license_map()
    preserve_when_unclaimed = get_preserve_fields(MachineModel, claim_fields)

    # 2. Pre-fetch all active claims, grouped by object_id (~1 query).
    claims_by_model = _build_claims_by_model()
    _status(f"Loaded {sum(len(v) for v in claims_by_model.values())} winning claims")

    # 3. Load all MachineModels (~1 query).
    all_models = list(MachineModel.objects.all())
    pre_slugs = {pm.pk: pm.slug for pm in all_models}

    # 4. Resolve each model in memory.
    for pm in all_models:
        winners = claims_by_model.get(pm.pk, {})
        _apply_resolution(
            pm,
            winners,
            claim_fields,
            field_defaults,
            fk_info,
            sfl_map,
            preserve_when_unclaimed,
        )

    # 5. Detect unique-field conflicts across all resolved models.
    resolve_unique_conflicts(all_models, "opdb_id", MachineModel)
    resolve_unique_conflicts(all_models, "slug", MachineModel, pre_slugs)

    # 6. Validate check constraints before writing.
    for pm in all_models:
        validate_check_constraints(pm)

    # 7. Set updated_at (auto_now not triggered by bulk_update).
    now = timezone.now()
    for pm in all_models:
        pm.updated_at = now

    # 8. Bulk write (~1 query, batched).
    update_fields = [*claim_fields.values(), "extra_data", "updated_at"]
    # batch_size=100 is optimal for SQLite (CASE WHEN overhead grows with
    # batch size × field count). PostgreSQL uses a more efficient UPDATE FROM
    # VALUES syntax and handles larger batches fine.
    MachineModel.objects.bulk_update(all_models, update_fields, batch_size=100)
    _status(f"Wrote {len(all_models)} models")

    # 9. Bulk-resolve relationship claims.
    all_model_ids = {pm.pk for pm in all_models}
    resolve_all_credits(subject_ids=all_model_ids)
    _status("Credits resolved")

    resolve_all_themes(subject_ids=all_model_ids)
    resolve_all_gameplay_features(subject_ids=all_model_ids)
    resolve_all_reward_types(subject_ids=all_model_ids)
    resolve_all_tags(subject_ids=all_model_ids)
    _status("Themes, features, reward types, tags resolved")

    resolve_all_model_abbreviations(subject_ids=all_model_ids)
    _status("Abbreviations resolved")

    from django.contrib.contenttypes.models import ContentType

    ct_mm = ContentType.objects.get_for_model(MachineModel)
    resolve_media_attachments(content_type_id=ct_mm.id, subject_ids=all_model_ids)
    _status("Media attachments resolved")

    return len(all_models)


# ------------------------------------------------------------------
# Bulk resolution helpers (used by resolve_machine_models)
# ------------------------------------------------------------------


def _build_claims_by_model() -> dict[int, dict[str, Claim]]:
    """Pre-fetch all active claims for MachineModel, pick winner per (object_id, claim_key).

    Returns {object_id: {claim_key: winning_claim}}.
    """
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(MachineModel)
    claims = ranked_claims(
        Claim.objects.filter(content_type=ct), "object_id", "claim_key"
    ).select_related("source__default_license")

    result: dict[int, dict[str, Claim]] = {}
    for claim in claims:
        model_winners = result.setdefault(claim.object_id, {})
        # First claim per (object_id, claim_key) group is the winner.
        if claim.claim_key not in model_winners:
            model_winners[claim.claim_key] = claim

    return result


def _apply_resolution(
    pm: MachineModel,
    winners: dict[str, Claim],
    claim_fields: dict[str, str],
    # field_defaults values are Django field defaults — scalars, None, or
    # callable output; see ``_helpers.get_field_defaults``.
    field_defaults: dict[str, Any],
    fk_info: FKInfo,
    sfl_map: SourceFieldLicenseMap | None = None,
    preserve_when_unclaimed: set[str] | None = None,
) -> None:
    """Apply claim winners to a MachineModel instance in memory."""
    # Reset claim-controlled fields to defaults — preserved fields keep
    # their existing value unless a winning claim explicitly sets them.
    _preserve = preserve_when_unclaimed or set()
    winner_attrs = {
        claim_fields[c.field_name]
        for c in winners.values()
        if c.field_name in claim_fields
    }
    for attr, default in field_defaults.items():
        if attr in _preserve and attr not in winner_attrs:
            continue
        setattr(pm, attr, default)

    # Fresh extra_data dict (never shared between models).
    extra_data: JsonBody = {}

    # Apply winners.
    for _claim_key, claim in winners.items():
        if claim.field_name in get_relationship_namespaces():
            continue
        if claim.field_name in claim_fields:
            attr = claim_fields[claim.field_name]
            if attr in fk_info.fk_fields:
                setattr(
                    pm,
                    attr,
                    _resolve_fk_generic(
                        MachineModel,
                        attr,
                        claim.value,
                        lookup=fk_info.lookups.get(attr),
                    ),
                )
            else:
                setattr(pm, attr, _coerce(MachineModel, attr, claim.value))
        else:
            extra_data[claim.field_name] = claim.value
            if claim.field_name in IMAGE_FIELDS:
                lic = resolve_effective_license(claim, sfl_map)
                extra_data[f"{claim.field_name}.__license_slug"] = (
                    lic.slug if lic else None
                )
                extra_data[f"{claim.field_name}.__permissiveness_rank"] = (
                    lic.permissiveness_rank if lic else None
                )

    pm.extra_data = extra_data
