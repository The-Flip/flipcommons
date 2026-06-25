"""Resolution logic for non-MachineModel entities.

Includes the generic _resolve_single() and _resolve_bulk() helpers,
entity-specific field maps, and public resolve_*() functions for
Manufacturer, Person, Theme, CorporateEntity, System, and Title.
Also handles taxonomy model resolution.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.core.types import JsonBody
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.validation import get_relationship_namespaces

from ._helpers import (
    _coerce,
    _resolve_fk_generic,
    build_fk_info,
    get_field_defaults,
    get_preserve_fields,
    resolve_unique_conflicts,
    validate_check_constraints,
)

logger = logging.getLogger(__name__)


def _sync_markdown_references(obj: ClaimControlledModel) -> None:
    """Sync RecordReference table for all markdown fields on the object.

    Always calls sync_references, even for empty fields, so that stale
    references are cleaned up when a field is blanked.
    """
    from apps.core.markdown import get_markdown_fields
    from apps.core.markdown.references import sync_references

    for field_name in get_markdown_fields(type(obj)):
        sync_references(obj, getattr(obj, field_name, "") or "")


# ------------------------------------------------------------------
# Generic single-object resolver
# ------------------------------------------------------------------


def _resolve_single(
    obj: ClaimControlledModel,
    direct_fields: dict[str, str],
) -> None:
    """Resolve active claims onto a single object with only direct fields.

    This is the single-object counterpart to ``_resolve_bulk()``.

    Resolvable fields are reset to their defaults, then active claim
    winners are applied.  UNIQUE fields are preserved when no claim
    exists (resetting them to a shared default like ``""`` would cause
    integrity errors in the bulk path and semantic inconsistency in the
    single path).  Non-unique fields with no active claim are
    blank/null after resolution.

    Mutates *obj* in memory; the caller is responsible for saving.
    """
    claims = ranked_claims(obj.claims.all(), "field_name")

    winners: dict[str, Claim] = {}
    for claim in claims:
        if claim.field_name not in winners:
            winners[claim.field_name] = claim

    # Reset resolvable fields to defaults.  Some fields must keep their
    # existing value when no winning claim exists — see _resolve_bulk().
    model_class = type(obj)
    field_defaults = get_field_defaults(model_class, direct_fields)
    preserve_when_unclaimed = get_preserve_fields(model_class, direct_fields)
    winner_attrs = {direct_fields[fn] for fn in winners if fn in direct_fields}
    for attr, default in field_defaults.items():
        if attr in preserve_when_unclaimed and attr not in winner_attrs:
            continue
        setattr(obj, attr, default)

    # Apply winners.
    has_extra_data = hasattr(obj, "extra_data")
    extra_data: JsonBody | None = {} if has_extra_data else None
    relationship_ns = get_relationship_namespaces()
    for field_name, claim in winners.items():
        # Relationship-namespace claims (media_attachment, credit, …) resolve
        # into their own tables, never extra_data — mirrors resolve_model().
        if field_name in relationship_ns:
            continue
        if field_name in direct_fields:
            attr = direct_fields[field_name]
            field = model_class._meta.get_field(attr)
            if field.is_relation:
                setattr(
                    obj,
                    attr,
                    _resolve_fk_generic(
                        model_class,
                        attr,
                        claim.value,
                    ),
                )
            else:
                setattr(obj, attr, _coerce(model_class, attr, claim.value))
        elif has_extra_data:
            assert extra_data is not None
            extra_data[field_name] = claim.value
    if has_extra_data:
        # extra_data lives on a concrete-subclass subset; runtime-guarded above.
        obj.extra_data = extra_data  # type: ignore[attr-defined]


# ------------------------------------------------------------------
# Generic bulk resolver
# ------------------------------------------------------------------


def _resolve_bulk(
    model_class: type[ClaimControlledModel],
    direct_fields: dict[str, str],
    object_ids: set[int] | None = None,
) -> int:
    """Bulk-resolve claims for all (or selected) instances of a model class.

    Pre-fetches all active claims in one query, resolves in memory, then
    writes back with a single bulk_update(). This is the bulk counterpart
    to _resolve_single().

    UNIQUE fields are preserved when no winning claim exists — resetting
    them to a shared default (e.g. ``""``) would cause IntegrityError
    when multiple objects lack claims for that field.

    FK fields in *direct_fields* are auto-detected and resolved by slug
    (or model-declared ``claim_fk_lookups`` override).

    Parameters:
        model_class: The Django model class to resolve.
        direct_fields: Maps claim field_name to model attribute name.
        object_ids: If provided, only resolve these object IDs. If None,
            resolve all instances.

    Returns the number of objects updated.
    """
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(model_class)

    # 1. Pre-fetch all active claims for this model class.
    claims_qs = ranked_claims(
        Claim.objects.filter(content_type=ct), "object_id", "field_name"
    )
    if object_ids is not None:
        claims_qs = claims_qs.filter(object_id__in=object_ids)

    # Group by object_id, pick winner per field_name.
    claims_by_obj: dict[int, dict[str, Claim]] = {}
    for claim in claims_qs:
        obj_winners = claims_by_obj.setdefault(claim.object_id, {})
        if claim.field_name not in obj_winners:
            obj_winners[claim.field_name] = claim

    # 2. Load objects.
    objs_qs = model_class.objects.all()  # type: ignore[attr-defined]
    if object_ids is not None:
        objs_qs = objs_qs.filter(pk__in=object_ids)
    all_objs = list(objs_qs)

    if not all_objs:
        return 0

    # 3. Compute field defaults once.
    field_defaults = get_field_defaults(model_class, direct_fields)

    preserve_when_unclaimed = get_preserve_fields(model_class, direct_fields)

    # Identify FK fields and pre-build lookups.
    fk_info = build_fk_info(model_class, direct_fields)

    # Check if model has extra_data field for unmatched claims.
    has_extra_data = hasattr(model_class, "extra_data")

    # Snapshot slugs before resolution for conflict revert.
    # Only check for global uniqueness if the slug field is actually unique.
    # django-stubs validates the field-name literal against the model's
    # declared fields; abstract ClaimControlledModel._meta is empty.
    slug_field = (
        model_class._meta.get_field("slug")  # type: ignore[misc]
        if "slug" in direct_fields
        else None
    )
    has_unique_slug = slug_field is not None and bool(
        getattr(slug_field, "unique", False)
    )
    pre_slugs = {obj.pk: obj.slug for obj in all_objs} if has_unique_slug else {}

    # 4. Resolve each object in memory.
    now = timezone.now()
    relationship_ns = get_relationship_namespaces()
    for obj in all_objs:
        winners = claims_by_obj.get(obj.pk, {})

        # Reset direct fields — preserved fields keep their existing
        # value unless a winning claim explicitly sets them.
        winner_attrs = {direct_fields[fn] for fn in winners if fn in direct_fields}
        for attr, default in field_defaults.items():
            if attr in preserve_when_unclaimed and attr not in winner_attrs:
                continue
            setattr(obj, attr, default)

        # Apply winners.
        extra_data: JsonBody | None = {} if has_extra_data else None
        for field_name, claim in winners.items():
            # Relationship-namespace claims (media_attachment, credit, …)
            # resolve into their own tables, never extra_data.
            if field_name in relationship_ns:
                continue
            if field_name in direct_fields:
                attr = direct_fields[field_name]
                if attr in fk_info.fk_fields:
                    setattr(
                        obj,
                        attr,
                        _resolve_fk_generic(
                            model_class,
                            attr,
                            claim.value,
                            lookup=fk_info.lookups.get(attr),
                        ),
                    )
                else:
                    setattr(obj, attr, _coerce(model_class, attr, claim.value))
            elif has_extra_data:
                assert extra_data is not None
                extra_data[field_name] = claim.value
        if has_extra_data:
            obj.extra_data = extra_data

        obj.updated_at = now

    # 4b. Detect unique-field conflicts across resolved objects.
    if has_unique_slug:
        resolve_unique_conflicts(all_objs, "slug", model_class, pre_slugs)

    # 5. Bulk write.  Cross-field CheckConstraints are enforced by the DB
    # on bulk_update — a violation aborts the whole batch with IntegrityError,
    # which is the desired ingest behaviour (source data is broken, stop).
    # Per-object Python-side validation was removed because each call issued
    # a savepoint + SELECT round trip, producing thousands of round trips per
    # bulk and triggering Postgres subtransaction SLRU overflow on managed DBs.
    update_fields = [*set(direct_fields.values()), "updated_at"]
    if has_extra_data:
        update_fields.append("extra_data")
    model_class.objects.bulk_update(all_objs, update_fields, batch_size=100)  # type: ignore[attr-defined]

    # Sync markdown backlinks (RecordReference) for bulk-resolved objects.
    from apps.core.markdown import get_markdown_fields

    if get_markdown_fields(model_class):
        for obj in all_objs:
            _sync_markdown_references(obj)

    return len(all_objs)


# ------------------------------------------------------------------
# Generic entity resolvers (model-driven)
# ------------------------------------------------------------------


def resolve_entity[T: ClaimControlledModel](obj: T) -> T:
    """Resolve all claim-controlled fields on any entity.

    Discovers claim-controlled fields by introspecting the model (via
    ``get_claim_fields``), resolves winners, applies them (including FK
    fields), saves, and syncs markdown references.
    """
    from apps.provenance.models import get_claim_fields

    model_class = type(obj)
    fields = get_claim_fields(model_class)
    original_slug = obj.slug
    _resolve_single(obj, fields)

    # Single-object slug conflict guard — only slug gets silent revert.
    # Other unique fields (e.g. name) rely on save() → IntegrityError
    # which execute_claims() catches and returns as 422.
    # Skip when slug isn't globally unique (e.g. Location, where slug is
    # unique-per-location_path); mirrors the bulk path's has_unique_slug
    # check.  django-stubs checks the ``slug=`` filter keyword against the
    # model's declared fields; abstract ClaimControlledModel._meta lists
    # none.  The concrete subclass always has slug.
    slug_field = model_class._meta.get_field("slug") if "slug" in fields else None
    slug_is_unique = slug_field is not None and bool(
        getattr(slug_field, "unique", False)
    )
    if (
        slug_is_unique
        and obj.slug
        and obj.slug != original_slug
        and model_class.objects.filter(slug=obj.slug)  # type: ignore[attr-defined]
        .exclude(pk=obj.pk)
        .exists()
    ):
        logger.warning(
            "Cannot resolve slug=%r on %s pk=%s: "
            "already owned by another object, reverting to %r",
            obj.slug,
            model_class.__name__,
            obj.pk,
            original_slug,
        )
        obj.slug = original_slug

    validate_check_constraints(obj)
    obj.save()
    _sync_markdown_references(obj)
    return obj


def resolve_all_entities(
    model_class: type[ClaimControlledModel], *, object_ids: set[int] | None = None
) -> int:
    """Bulk-resolve all claim-controlled fields for all instances of a model.

    Discovers claim-controlled fields by introspecting the model.
    """
    from apps.provenance.models import get_claim_fields

    fields = get_claim_fields(model_class)
    return _resolve_bulk(model_class, fields, object_ids=object_ids)
