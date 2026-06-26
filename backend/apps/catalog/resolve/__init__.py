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

from typing import Any

from apps.core.types import JsonBody
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.licensing import (
    SourceFieldLicenseMap,
    build_source_field_license_map,
)
from apps.provenance.models import Claim
from apps.provenance.validation import get_relationship_namespaces

from ..models import MachineModel
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
    validate_check_constraints,
)
from ._image_fields import _stamp_image_license
from ._media import resolve_media_attachments
from ._relationships import (
    resolve_all_corporate_entity_locations,
    resolve_all_credits,
    resolve_all_gameplay_features,
    resolve_all_model_abbreviations,
    resolve_all_reward_types,
    resolve_all_series_credits,
    resolve_all_tags,
    resolve_all_themes,
    resolve_all_title_abbreviations,
    resolve_corporate_entity_aliases,
    resolve_gameplay_feature_aliases,
    resolve_manufacturer_aliases,
    resolve_person_aliases,
    resolve_reward_type_aliases,
    resolve_theme_aliases,
)


def resolve_model(machine_model: MachineModel) -> MachineModel:
    """Resolve all active claims into the given MachineModel's fields.

    Picks the winning claim per claim_key: highest effective priority
    (from source or user profile), then most recent created_at as tiebreaker.
    Delegates field application to ``_apply_resolution()``.

    Returns the saved MachineModel.
    """
    # Fetch and pick winners (single-object).
    claims = ranked_claims(machine_model.claims.all(), "claim_key").select_related(
        "actor__source__default_license"
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
    _apply_resolution(
        machine_model,
        winners,
        claim_fields,
        field_defaults,
        fk_info,
        sfl_map,
        preserve_when_unclaimed,
    )

    # Cross-reference uniqueness (slug, opdb_id, …) is not resolution's concern:
    # the DB unique constraint is the source of truth. A collision raises
    # IntegrityError on save(), which execute_claims() turns into a 422 on the
    # interactive path — exactly as the non-unique ``name`` field already does.
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
            _stamp_image_license(extra_data, claim, sfl_map)

    pm.extra_data = extra_data
