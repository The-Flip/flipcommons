"""Scalar and FK claim resolution for claim-controlled entities.

The generic per-object apply loop (:func:`_apply_claims`) plus the single-object
and bulk resolvers that drive it, and the public :func:`resolve_entity` /
:func:`resolve_all_entities` entry points that introspect each model's claim
fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from django.db import models
from django.utils import timezone

from apps.core.types import (
    ClaimFieldMap,
    ClaimFieldName,
    ClaimSubjectId,
    JsonBody,
)
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.licensing import (
    SourceFieldLicenseMap,
    build_source_field_license_map,
)
from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.validation import get_relationship_namespaces

from ._engine import pick_winners
from ._helpers import (
    _coerce,
    _resolve_fk_generic,
    build_fk_info,
    get_field_defaults,
    get_nullable_unique_fields,
    get_preserve_fields,
    resolve_unique_conflicts,
    validate_check_constraints,
)
from ._image_fields import IMAGE_FIELDS, _stamp_image_license


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
# Per-object apply loop
# This is shared between bulk and single-object claims resolution.
# ------------------------------------------------------------------

type FKLookups = Mapping[str, Mapping[int, models.Model]]
"""Read-only covariant view of ``FKTargetLookups`` — the apply loop only reads
the prefetched FK index, so the param accepts any mapping shape."""


@dataclass(frozen=True, slots=True)
class ScalarApplyContext:
    """The per-``model_class`` invariants of a scalar resolve pass.

    Built once and passed to :func:`_apply_claims` for every object.
    ``fk_lookups`` is ``None`` to resolve each FK by querying its target by PK,
    or a pre-built ``{attr: {pk: instance}}`` map to resolve FKs from memory.
    """

    model_class: type[ClaimControlledModel]
    direct_fields: ClaimFieldMap
    field_defaults: Mapping[str, object]
    preserve_when_unclaimed: AbstractSet[str]
    fk_lookups: FKLookups | None
    sfl_map: SourceFieldLicenseMap | None


def _apply_claims(
    obj: ClaimControlledModel,
    winners: Mapping[ClaimFieldName, Claim],
    ctx: ScalarApplyContext,
) -> None:
    """Reset *obj*'s resolvable fields to defaults, then apply its winning claims.

    FK fields resolve via :func:`_resolve_fk_generic` (querying when
    ``ctx.fk_lookups`` is ``None``, else the pre-built pk→instance dict),
    scalars via :func:`_coerce`, and unmatched claims land in ``extra_data`` with
    the image-license stamp. Mutates *obj*; the caller handles validation,
    conflict resolution and saving.
    """
    model_class = ctx.model_class
    direct_fields = ctx.direct_fields

    # Reset resolvable fields to defaults. Preserved fields (UNIQUE, non-nullable
    # FK) keep their existing value unless a winning claim explicitly sets them.
    winner_attrs = {direct_fields[fn] for fn in winners if fn in direct_fields}
    for attr, default in ctx.field_defaults.items():
        if attr in ctx.preserve_when_unclaimed and attr not in winner_attrs:
            continue
        setattr(obj, attr, default)

    # Apply winners.
    has_extra_data = hasattr(model_class, "extra_data")
    extra_data: JsonBody | None = {} if has_extra_data else None
    relationship_ns = get_relationship_namespaces()
    for field_name, claim in winners.items():
        # Relationship-namespace claims (media_attachment, credit, …) resolve
        # into their own tables, never extra_data.
        if field_name in relationship_ns:
            continue
        if field_name in direct_fields:
            attr = direct_fields[field_name]
            field = model_class._meta.get_field(attr)
            if field.is_relation:
                lookup = ctx.fk_lookups.get(attr) if ctx.fk_lookups else None
                setattr(
                    obj,
                    attr,
                    _resolve_fk_generic(model_class, attr, claim.value, lookup=lookup),
                )
            else:
                setattr(obj, attr, _coerce(model_class, attr, claim.value))
        elif has_extra_data:
            assert extra_data is not None
            extra_data[field_name] = claim.value
            _stamp_image_license(extra_data, claim, ctx.sfl_map)
    if has_extra_data:
        # extra_data lives on a concrete-subclass subset; runtime-guarded above.
        obj.extra_data = extra_data  # type: ignore[attr-defined]


# ------------------------------------------------------------------
# Generic single-object resolver
# ------------------------------------------------------------------


def _resolve_single(
    obj: ClaimControlledModel,
    direct_fields: ClaimFieldMap,
) -> None:
    """Resolve active claims onto a single object with only direct fields.

    Resolvable fields are reset to their defaults, then active claim winners are
    applied.  UNIQUE fields are preserved when no claim exists; non-unique fields
    with no active claim are blank/null after resolution. Uniqueness conflicts
    are left to the DB constraint — there is no in-batch de-confliction here.

    Mutates *obj* in memory; the caller is responsible for saving.
    """
    claims = ranked_claims(obj.claims.all(), "field_name")
    # Prefetch source.default_license for extra_data models — image-field claims
    # denormalize their license from it.
    if hasattr(obj, "extra_data"):
        claims = claims.select_related("actor__source__default_license")

    winners = pick_winners(claims, lambda c: c.object_id, lambda c: c.field_name).get(
        obj.pk, {}
    )

    model_class = type(obj)
    # Image fields denormalize their effective license into extra_data; build
    # the SourceFieldLicense map once iff a winning claim is an image field.
    sfl_map = (
        build_source_field_license_map()
        if any(fn in IMAGE_FIELDS for fn in winners)
        else None
    )
    ctx = ScalarApplyContext(
        model_class=model_class,
        direct_fields=direct_fields,
        field_defaults=get_field_defaults(model_class, direct_fields),
        preserve_when_unclaimed=get_preserve_fields(model_class, direct_fields),
        fk_lookups=None,
        sfl_map=sfl_map,
    )
    _apply_claims(obj, winners, ctx)


# ------------------------------------------------------------------
# Generic bulk resolver
# ------------------------------------------------------------------


def _resolve_bulk(
    model_class: type[ClaimControlledModel],
    direct_fields: ClaimFieldMap,
    object_ids: set[ClaimSubjectId] | None = None,
) -> int:
    """Bulk-resolve claims for all (or selected) instances of a model class.

    Pre-fetches all active claims in one query, resolves in memory, then
    writes back with a single bulk_update().

    UNIQUE fields are preserved when no winning claim exists — resetting
    them to a shared default (e.g. ``""``) would cause IntegrityError
    when multiple objects lack claims for that field.

    FK fields in *direct_fields* are auto-detected and resolved by the
    target PK stored in the claim value.

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
    # Models with extra_data may carry image-field claims, whose license is
    # denormalized into extra_data from source.default_license; prefetch it so
    # the per-claim stamp stays query-free.
    if hasattr(model_class, "extra_data"):
        claims_qs = claims_qs.select_related("actor__source__default_license")

    # Group by object_id, pick winner per field_name.
    claims_by_obj = pick_winners(
        claims_qs, lambda c: c.object_id, lambda c: c.field_name
    )

    # Image fields denormalize their effective license into extra_data; build
    # the SourceFieldLicense map once iff a winning claim is an image field.
    sfl_map = (
        build_source_field_license_map()
        if any(fn in IMAGE_FIELDS for w in claims_by_obj.values() for fn in w)
        else None
    )

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

    # Identify FK fields and pre-fetch the targets the winning claims reference.
    fk_info = build_fk_info(model_class, direct_fields, claims_by_obj)

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

    # 4. Resolve each object in memory.  The pre-built FK lookups resolve every
    # batch member from memory, with no per-object FK query.
    now = timezone.now()
    ctx = ScalarApplyContext(
        model_class=model_class,
        direct_fields=direct_fields,
        field_defaults=field_defaults,
        preserve_when_unclaimed=preserve_when_unclaimed,
        fk_lookups=fk_info.lookups,
        sfl_map=sfl_map,
    )
    for obj in all_objs:
        _apply_claims(obj, claims_by_obj.get(obj.pk, {}), ctx)
        obj.updated_at = now

    # 4b. Detect unique-field conflicts across resolved objects.
    if has_unique_slug:
        resolve_unique_conflicts(all_objs, "slug", model_class, pre_slugs)
    # Nullable single-column unique fields (external IDs like opdb_id,
    # wikidata_id): an in-batch collision clears the loser to None rather than
    # aborting the whole batch with IntegrityError. Discovered by introspection,
    # so every such field is covered.
    for unique_field in get_nullable_unique_fields(model_class, direct_fields):
        resolve_unique_conflicts(all_objs, unique_field, model_class)

    # 5. Bulk write.  Cross-field CheckConstraints are enforced by the DB
    # on bulk_update — a violation aborts the whole batch with IntegrityError,
    # which is the desired ingest behaviour (source data is broken, stop).
    # Per-object Python-side validation is deliberately skipped here: a savepoint
    # + SELECT round trip per object produces thousands of round trips per bulk
    # and triggers Postgres subtransaction SLRU overflow on managed DBs.
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
    _resolve_single(obj, fields)

    # Cross-reference uniqueness (slug, opdb_id, …) is not resolution's concern:
    # the DB unique constraint is the source of truth. A collision raises
    # IntegrityError on save(), which execute_claims() turns into a 422 on the
    # interactive path — exactly as the non-unique ``name`` field already does.
    validate_check_constraints(obj)
    obj.save()
    _sync_markdown_references(obj)
    return obj


def resolve_all_entities(
    model_class: type[ClaimControlledModel],
    *,
    object_ids: set[ClaimSubjectId] | None = None,
) -> int:
    """Bulk-resolve all claim-controlled fields for all instances of a model.

    Discovers claim-controlled fields by introspecting the model.
    """
    from apps.provenance.models import get_claim_fields

    fields = get_claim_fields(model_class)
    return _resolve_bulk(model_class, fields, object_ids=object_ids)
