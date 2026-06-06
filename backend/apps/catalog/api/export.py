"""Model-driven bulk-export API: ``GET /api/export/<entity-plural>/``.

One cached, flat, slug-keyed dump per catalog entity — the resolved shape (one
canonical value per field), not the claim graph. Built so adding a catalog
entity needs no new endpoint: the field set is discovered from the claim-field
partition (``get_claim_fields`` for scalars + FKs) plus the relationship-claim
registry (M2M / list relations), with a small per-entity ``ExportSpec`` for the
things introspection can't express (exempt fields, relation shapes, canonical
derived fields). See plans/model_driven_metadata and the bulk-export plan doc.

NOTE on the approved plan: ``get_claim_fields`` returns scalars + FKs only —
M2M/relationship claims live in a separate registry and are heterogeneous in
shape, so relationships are declared per entity via ``ExportSpec.relations``
rather than falling out of one introspection call.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Count, Max, Min, Q, QuerySet, Subquery
from django.http import HttpRequest, HttpResponse
from ninja import Router, Schema
from pydantic import Field as PydanticField
from pydantic import TypeAdapter, create_model

from apps.catalog.models import CatalogModel
from apps.core.entity_types import all_linkable_models, get_linkable_model
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.rate_limits import RateLimitSpec, check_and_record_ip
from apps.core.schemas import RateLimitErrorSchema
from apps.media.models import MediaSupportedModel
from apps.provenance.helpers import active_claims as _active_claims
from apps.provenance.helpers import claims_prefetch
from apps.provenance.licensing import (
    SourceFieldLicenseMap,
    build_source_field_license_map,
    resolve_effective_license,
)
from apps.provenance.models.introspection import get_claim_fields
from apps.provenance.schemas import AttributionSchema
from apps.provenance.validation import get_all_relationship_schemas

from ..cache import export_key, get_cached_response, set_cached_response
from .images import extract_image_attribution, extract_image_urls, media_prefetch

# The "export" tag is the opt-in marker for the public API reference: /api-docs
# shows only export-tagged endpoints (and uses the tag as the section heading).
# The bulk export is the sole documented API; every other catalog route is
# undocumented-by-default — see config/api.py.
export_router = Router(tags=["export"])

# Claim fields handled by the shared base / elsewhere, never as plain claim
# scalars: name + slug are identity (public_id/name on the base); description is
# the rich-text base field; status is lifecycle-internal and the export is
# active-only, so it's blanket-exempt on every entity.
_BASE_HANDLED = frozenset({"name", "slug", "description", "status"})

# Per-entity System-internal / API-suppressed claim fields kept OUT of the dump.
_MODERATION = frozenset({"needs_review", "needs_review_notes"})  # internal review notes
_RATINGS = frozenset({"ipdb_rating", "pinside_rating"})  # already cut from the API


# Per-IP rate limit for the public export, via the project's sanctioned IP limiter
# (X-Real-IP, trust-flag-gated, fail-closed; structured 429 + Retry-After). One
# shared bucket across all export endpoints, so the limit is a per-IP full-sync
# budget (rationale + numbers: settings.EXPORT_RATELIMIT_IP). Built per-request
# from settings (like the signup limiters) so the cap is tunable at runtime
# without a deploy — see apps.accounts.api.signup._spec for the same pattern.
def _export_rate_limit_spec() -> RateLimitSpec:
    limit, window = settings.EXPORT_RATELIMIT_IP
    return RateLimitSpec(bucket="export", limit=limit, window_seconds=window)


def export_rate_limit_summary() -> str:
    """Human-readable budget for the public API description, e.g. "roughly 6
    full exports per hour".

    Derived from the configured spec and the endpoint count (one request per
    entity = one full dump), so the published description tracks
    ``EXPORT_RATELIMIT_IP`` instead of carrying a hand-typed number that drifts.
    """
    limit, window = settings.EXPORT_RATELIMIT_IP
    requests_per_full_export = len(EXPORT_ENTITY_TYPES)
    full_exports_per_hour = round(limit / requests_per_full_export * 3600 / window)
    return f"roughly {full_exports_per_hour} full exports per hour"


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationSpec:
    """One claim relationship serialized as a flat, slug-keyed value.

    ``accessor`` is the model attribute returning the related manager.
    ``shape`` picks the output: ``slugs`` → ``list[str]`` of ``public_id``;
    ``strings`` → ``list[str]`` of ``.value``; ``credits`` → ``list[{person,
    role}]``. ``via`` hops one FK on each row before reading ``public_id``
    (e.g. a through row's ``location``). ``prefetch`` are the
    ``prefetch_related`` paths it needs.
    """

    accessor: str
    shape: str  # "slugs" | "strings" | "credits"
    prefetch: tuple[str, ...]
    via: str | None = None
    description: str = ""  # OpenAPI field doc; a default is generated if blank


@dataclass(frozen=True)
class DerivedField:
    """A canonical derived field (Django can't introspect the business rule).

    ``py_type`` is the schema type; ``attr`` is the queryset-annotation
    attribute the serializer reads off the instance; ``description`` is the
    OpenAPI field doc.
    """

    py_type: Any
    attr: str
    description: str


@dataclass(frozen=True)
class ExportSpec:
    """Per-entity export config — everything introspection can't infer."""

    model: type[CatalogModel]
    export_exempt: frozenset[str] = frozenset()
    relations: Mapping[str, RelationSpec] = field(default_factory=dict)
    derived: Mapping[str, DerivedField] = field(default_factory=dict)
    annotate: Callable[[QuerySet[Any]], QuerySet[Any]] | None = None


class CreditExportSchema(Schema):
    """A credit: the contributing person and their role, both by slug."""

    person: str = PydanticField(description="Slug of the credited person.")
    role: str = PydanticField(description="Slug of the credit role (e.g. `design`).")


# Implementation note (kept out of the public schema description below): we emit
# the description as source text, not rendered HTML — rendering resolves the
# inline [[type:id]] entity links per row, which is a query storm at bulk scale.
# Link tokens are instead bulk-resolved to public_ids once per build in the serializer.
class DescriptionExportSchema(Schema):
    """An entity's description: Markdown source text plus license attribution."""

    text: str = PydanticField(
        default="",
        description=(
            "The description as Markdown. Inline entity links appear as "
            "`[[type:public_id]]` tokens referencing other catalog records by "
            "their public id (usually a slug)."
        ),
    )
    attribution: AttributionSchema | None = PydanticField(
        default=None,
        description="License and source for the description text, for lawful reuse.",
    )


class EntityExportSchema(Schema):
    """Common base for every export row: identity, freshness, description."""

    public_id: str = PydanticField(
        description="The record's stable public identifier (usually its slug)."
    )
    name: str = PydanticField(description="The record's display name.")
    last_modified: datetime = PydanticField(
        description=(
            "When the record last changed. For parent entities, reflects the "
            "most recent change to any child."
        )
    )
    description: DescriptionExportSchema = PydanticField(
        description="The record's description text and its license attribution."
    )


# ---------------------------------------------------------------------------
# Field-type mapping (Django field -> pydantic type)
# ---------------------------------------------------------------------------


def _scalar_py_type(f: models.Field[Any, Any]) -> Any:  # noqa: ANN401 — returns a dynamic pydantic field type
    if isinstance(f, ArrayField):
        inner = _scalar_py_type(f.base_field)
        return list[inner] | None if f.null else list[inner]  # type: ignore[valid-type]
    if isinstance(f, models.JSONField):
        return Any  # arbitrary structured JSON (e.g. Location.divisions)
    if isinstance(f, models.ForeignKey):
        base: Any = str
    elif isinstance(f, models.BooleanField):
        base = bool
    elif isinstance(f, models.DecimalField):
        base = str
    elif isinstance(f, models.FloatField):
        base = float
    elif isinstance(f, models.IntegerField):
        base = int
    else:
        base = str  # char / text / slug / date (emitted as ISO string)
    return base | None if f.null else base


def _json_scalar(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _fk_slug(obj: models.Model, name: str) -> str | None:
    related = getattr(obj, name, None)
    return related.public_id if related is not None else None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _claim_scalar_fields(spec: ExportSpec) -> dict[str, models.Field[Any, Any]]:
    """Claim scalar/FK fields for the model, minus base-handled + exempt."""
    out: dict[str, models.Field[Any, Any]] = {}
    for name in get_claim_fields(spec.model):
        if name in _BASE_HANDLED or name in spec.export_exempt:
            continue
        f = spec.model._meta.get_field(name)
        assert isinstance(f, models.Field)  # claim fields are concrete columns
        out[name] = f
    return out


def _relationship_namespaces(model: type[CatalogModel]) -> set[str]:
    """Claim-relationship namespaces registered for this model (for drift-guard)."""
    return {
        ns
        for ns, schema in get_all_relationship_schemas().items()
        if model in schema.valid_subjects
    }


# ---------------------------------------------------------------------------
# Schema construction (runtime create_model -> concrete OpenAPI component)
# ---------------------------------------------------------------------------


def _claim_field_doc(f: models.Field[Any, Any]) -> str:
    """OpenAPI doc for a claim field: model help_text, else a derived fallback."""
    if f.help_text:
        # Model-sourced: help_text is the single doc source (also drives admin
        # + IDE hover). Backfill help_text on a model field to improve this.
        return str(f.help_text)
    if isinstance(f, models.ForeignKey):
        # related_model is "self" in the stubs for self-referential FKs; at
        # runtime it's always the resolved model class.
        related = f.related_model
        model = f.model if isinstance(related, str) else related
        return f"Slug of the associated {model._meta.verbose_name}."
    return f"{str(f.verbose_name).capitalize()}."


def _relation_doc(key: str, rel: RelationSpec) -> str:
    if rel.description:
        return rel.description
    label = key.replace("_", " ")
    if rel.shape == "credits":
        return "Production credits, as person-slug / role-slug pairs."
    if rel.shape == "strings":
        return f"List of {label}."
    return f"Slugs of the associated {label}."


def _build_schema(spec: ExportSpec) -> type[EntityExportSchema]:
    # Every field is always emitted by _serialize_row, so all are required (no
    # defaults); nullability lives in the type (e.g. `str | None`). This keeps
    # the schema accurate and makes a missing field fail loudly in DEBUG.
    fields: dict[str, Any] = {}
    for name, f in _claim_scalar_fields(spec).items():
        fields[name] = (
            _scalar_py_type(f),
            PydanticField(description=_claim_field_doc(f)),
        )
    if issubclass(spec.model, MediaSupportedModel):
        fields["thumbnail_url"] = (
            str | None,
            PydanticField(description="URL of the primary thumbnail image, or null."),
        )
        fields["hero_image_url"] = (
            str | None,
            PydanticField(description="URL of the larger hero/display image, or null."),
        )
        fields["image_attribution"] = (
            AttributionSchema | None,
            PydanticField(
                description=(
                    "License and source for the image when it is third-party; "
                    "null for site-owned uploads."
                ),
            ),
        )
    for key, rel in spec.relations.items():
        item: Any = CreditExportSchema if rel.shape == "credits" else str
        fields[key] = (list[item], PydanticField(description=_relation_doc(key, rel)))
    for key, dfield in spec.derived.items():
        fields[key] = (dfield.py_type, PydanticField(description=dfield.description))
    # The base public_id doc says "usually its slug"; override for entities whose
    # public_id isn't a slug (only Location, public_id_field="location_path").
    if spec.model.public_id_field != "slug":
        fields["public_id"] = (
            str,
            PydanticField(
                description=(
                    "The record's stable public identifier (its "
                    f"{spec.model.public_id_field})."
                )
            ),
        )
    return create_model(
        f"{spec.model.__name__}ExportSchema",
        __base__=EntityExportSchema,
        **fields,
    )


# ---------------------------------------------------------------------------
# Queryset + serialization
# ---------------------------------------------------------------------------


def _build_qs(spec: ExportSpec) -> QuerySet[Any]:
    model = spec.model
    fk_names = [
        n
        for n, f in _claim_scalar_fields(spec).items()
        if isinstance(f, models.ForeignKey)
    ]
    qs: QuerySet[Any] = (
        model.objects.active()
        .annotate(_last_modified=model.lastmod_expression())
        .select_related(*fk_names)
        # Only description claims — attribution needs no other field, and the
        # full claims_prefetch would drag the whole claim table at bulk scale.
        .prefetch_related(claims_prefetch(field_names=("description",)))
    )
    if issubclass(spec.model, MediaSupportedModel):
        qs = qs.prefetch_related(media_prefetch())
    for rel in spec.relations.values():
        qs = qs.prefetch_related(*rel.prefetch)
    if spec.annotate is not None:
        qs = spec.annotate(qs)
    return qs


def _serialize_relation(obj: CatalogModel, rel: RelationSpec) -> list[Any]:
    # Referential-integrity note: relation (and FK) slugs are NOT lifecycle-
    # filtered, while every dump is active-only. Lifecycle usage-blockers stop a
    # referenced entity being soft-deleted while linked for most relations
    # (Theme/Tag/RewardType/GameplayFeature block on machine_models), so dangling
    # refs are rare — but e.g. Manufacturer has no blocker, so a soft-deleted
    # manufacturer could leave a slug absent from /export/manufacturers/. Accepted
    # as a rare edge; active-filter the relations here if stricter cross-dump
    # integrity is needed.
    manager = getattr(obj, rel.accessor)
    rows = manager.all() if hasattr(manager, "all") else manager
    if rel.shape == "slugs":
        if rel.via is not None:
            return [getattr(r, rel.via).public_id for r in rows]
        return [r.public_id for r in rows]
    if rel.shape == "strings":
        return [r.value for r in rows]
    if rel.shape == "credits":
        return [{"person": c.person.public_id, "role": c.role.public_id} for c in rows]
    raise ValueError(f"Unknown relation shape: {rel.shape!r}")


# Storage-format entity link: ``[[<entity-type>:id:<pk>]]``.
_LINK_RE = re.compile(r"\[\[([a-z-]+):id:(\d+)\]\]")


class _LinkRef(NamedTuple):
    """A storage entity-link target: the entity type and the referenced row pk."""

    entity_type: str
    pk: int


# Resolves a [[type:id:pk]] token to the target's public_id, in bulk.
type _LinkMap = dict[_LinkRef, str]


def _build_link_map(texts: list[str]) -> _LinkMap:
    """Resolve every ``[[type:id:pk]]`` token across *texts* to a public_id, in
    bounded queries (one per referenced entity type), so per-row substitution
    is query-free. Unknown types/ids are left as their pk by the substituter.
    (public_id is a slug for most entities, a location_path for Location.)
    """
    refs: dict[str, set[int]] = defaultdict(set)
    for text in texts:
        for m in _LINK_RE.finditer(text):
            refs[m.group(1)].add(int(m.group(2)))
    link_map: _LinkMap = {}
    for entity_type, ids in refs.items():
        try:
            model = get_linkable_model(entity_type)
        except ValueError:
            continue
        for pk, public_id in model._default_manager.filter(pk__in=ids).values_list(
            "pk", model.public_id_field
        ):
            link_map[_LinkRef(entity_type, pk)] = public_id
    return link_map


# Inline citation marker ``[[cite:N]]`` — the only id-only link type
# (public_id_field=None); its token carries an internal CitationInstance pk.
def _id_only_link_re() -> re.Pattern[str]:
    """Match ``[[<name>:N]]`` tokens for every id-only link type (``cite`` today,
    plus any future ``public_id_field=None`` type) — derived from the wikilinks
    registry so a new one can't silently leak a raw pk. Keyed on the registered
    names, so it never strips a resolved ``[[type:public_id]]`` (even a numeric
    slug). Matches nothing if there are no id-only types.

    Evaluated fresh per export build (the caller computes it once and threads it),
    NOT cached for the process lifetime, so ``LinkType.is_enabled``'s runtime
    toggle is honored.
    """
    from apps.core.wikilinks import get_enabled_link_types

    names = [
        re.escape(lt.name)
        for lt in get_enabled_link_types()
        if lt.public_id_field is None
    ]
    return (
        re.compile(rf"\[\[(?:{'|'.join(names)}):\d+\]\]")
        if names
        else re.compile(r"(?!)")
    )


def _resolve_links(text: str, link_map: _LinkMap, id_only_re: re.Pattern[str]) -> str:
    """Rewrite ``[[type:id:pk]]`` tokens to public_id-keyed ``[[type:public_id]]``.

    Tokens we can't resolve to a public_id are dropped, never emitted with their
    raw pk: a broken/dangling link (id not found) or an id-only marker (citations)
    would otherwise leak an internal database id into the public dump.
    """

    def _sub(m: re.Match[str]) -> str:
        entity_type, pk = m.group(1), int(m.group(2))
        public_id = link_map.get(_LinkRef(entity_type, pk))
        return f"[[{entity_type}:{public_id}]]" if public_id else ""

    return id_only_re.sub("", _LINK_RE.sub(_sub, text))


def _serialize_description(
    obj: CatalogModel,
    sfl_map: SourceFieldLicenseMap,
    link_map: _LinkMap,
    id_only_re: re.Pattern[str],
) -> dict[str, Any]:
    """Description source text + winning-claim attribution, query-free.

    ``text`` is public_id-keyed authoring markdown (link tokens pre-resolved in
    bulk via *link_map* — no per-row id→public_id lookup). Attribution reads the
    targeted
    ``active_claims`` prefetch (description claims only) and the precomputed
    *sfl_map* — no markdown rendering, no per-row license-map rebuild.
    """
    # description is a MarkdownField(blank=True) on every CatalogModel — always a
    # str ("" when blank), and _resolve_links("") == "".
    text = _resolve_links(obj.description, link_map, id_only_re)
    attribution: AttributionSchema | None = None
    for claim in _active_claims(obj):
        if claim.field_name == "description":
            lic = resolve_effective_license(claim, sfl_map)
            attribution = AttributionSchema(
                license_slug=lic.slug if lic else None,
                license_name=lic.short_name if lic else None,
                license_url=lic.url if lic else None,
                permissiveness_rank=lic.permissiveness_rank if lic else None,
                requires_attribution=lic.requires_attribution if lic else False,
                source_name=claim.source.name if claim.source else None,
                source_url=claim.source.url if claim.source else None,
                attribution_text=claim.citation or None,
            )
            break
    return {
        "text": text,
        "attribution": attribution.model_dump() if attribution else None,
    }


def _serialize_row(
    obj: CatalogModel,
    spec: ExportSpec,
    *,
    min_rank: int,
    sfl_map: SourceFieldLicenseMap,
    link_map: _LinkMap,
    id_only_re: re.Pattern[str],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "public_id": obj.public_id,
        "name": obj.name,
        "last_modified": obj.last_modified.isoformat(),
        "description": _serialize_description(obj, sfl_map, link_map, id_only_re),
    }
    for name, f in _claim_scalar_fields(spec).items():
        if isinstance(f, models.ForeignKey):
            row[name] = _fk_slug(obj, name)
        else:
            row[name] = _json_scalar(getattr(obj, name))
    if issubclass(spec.model, MediaSupportedModel):
        media = getattr(obj, "all_media", None)
        extra = getattr(obj, "extra_data", None) or {}
        thumb, hero = extract_image_urls(extra, media, min_rank=min_rank)
        row["thumbnail_url"] = thumb
        row["hero_image_url"] = hero
        att = extract_image_attribution(extra, media, min_rank=min_rank)
        row["image_attribution"] = att.model_dump() if att else None
    for key, rel in spec.relations.items():
        row[key] = _serialize_relation(obj, rel)
    for key, dfield in spec.derived.items():
        row[key] = _json_scalar(getattr(obj, dfield.attr, None))
    return row


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _rel(
    accessor: str, shape: str, *prefetch: str, via: str | None = None
) -> RelationSpec:
    return RelationSpec(
        accessor=accessor, shape=shape, prefetch=prefetch or (accessor,), via=via
    )


def _build_registry() -> dict[type[CatalogModel], ExportSpec]:
    from apps.catalog.models import (
        CorporateEntity,
        GameplayFeature,
        MachineModel,
        Manufacturer,
        Series,
        Theme,
        Title,
    )

    specs: list[ExportSpec] = [
        ExportSpec(
            model=MachineModel,
            export_exempt=_RATINGS,
            relations={
                "themes": _rel("themes", "slugs"),
                "tags": _rel("tags", "slugs"),
                "reward_types": _rel("reward_types", "slugs"),
                "gameplay_features": _rel("gameplay_features", "slugs"),
                "abbreviations": _rel("abbreviations", "strings"),
                "credits": _rel(
                    "credits", "credits", "credits__person", "credits__role"
                ),
            },
        ),
        ExportSpec(
            model=Title,
            export_exempt=_MODERATION,
            relations={"abbreviations": _rel("abbreviations", "strings")},
            derived={
                "year": DerivedField(
                    int | None,
                    "_export_year",
                    "Release year, derived from this title's first model.",
                ),
                "manufacturer": DerivedField(
                    str | None,
                    "_export_mfr",
                    "Manufacturer slug, derived from this title's first model.",
                ),
            },
            annotate=_annotate_title,
        ),
        ExportSpec(
            model=Manufacturer,
            derived={
                "model_count": DerivedField(
                    int,
                    "_export_model_count",
                    "Number of non-variant machine models by this manufacturer.",
                ),
                "year_min": DerivedField(
                    int | None,
                    "_export_year_min",
                    "Earliest model year for this manufacturer.",
                ),
                "year_max": DerivedField(
                    int | None,
                    "_export_year_max",
                    "Latest model year for this manufacturer.",
                ),
            },
            annotate=_annotate_manufacturer,
        ),
        ExportSpec(
            model=CorporateEntity,
            relations={
                "locations": _rel(
                    "locations", "slugs", "locations__location", via="location"
                ),
            },
        ),
        ExportSpec(
            model=Theme,
            relations={
                "parents": _rel("parents", "slugs"),
            },
        ),
        ExportSpec(
            model=GameplayFeature,
            relations={
                "parents": _rel("parents", "slugs"),
            },
        ),
        ExportSpec(
            model=Series,
            relations={
                "credits": _rel(
                    "credits", "credits", "credits__person", "credits__role"
                ),
            },
        ),
    ]
    by_model = {s.model: s for s in specs}
    # Every other catalog entity gets the default (common + scalars/FKs).
    for model in all_linkable_models():
        if issubclass(model, CatalogModel) and model not in by_model:
            by_model[model] = ExportSpec(model=model)

    # Aliases are uniform (every AliasModel parent has an ``aliases`` relation of
    # string values) and registry-known, so derive them rather than hand-listing
    # per entity — otherwise an entity with aliases is silently dropped from the
    # dump (e.g. Manufacturer/Person/Location/RewardType were).
    from apps.catalog._alias_registry import discover_alias_types

    alias_models = {at.parent_model for at in discover_alias_types()}
    for model, spec in by_model.items():
        if model in alias_models and "aliases" not in spec.relations:
            by_model[model] = replace(
                spec,
                relations={**spec.relations, "aliases": _rel("aliases", "strings")},
            )
    return by_model


def _annotate_title(qs: QuerySet[Any]) -> QuerySet[Any]:
    from apps.catalog.models import Title

    # Single-sourced "first model" rule (do not reimplement) — see title.py.
    first = Title.first_model_subquery()
    annotated: QuerySet[Any] = qs.annotate(
        _export_year=Subquery(first.values("year")[:1]),
        _export_mfr=Subquery(first.values("corporate_entity__manufacturer__slug")[:1]),
    )
    return annotated


def _annotate_manufacturer(qs: QuerySet[Any]) -> QuerySet[Any]:
    # active_status_q matches LifecycleManager.active() (status active OR null) —
    # a plain status="active" would undercount legacy null-status ingest rows that
    # DO appear in the /export/models/ dump.
    nonvariant = Q(entities__models__variant_of__isnull=True) & active_status_q(
        "entities__models"
    )
    annotated: QuerySet[Any] = qs.annotate(
        _export_model_count=Count("entities__models", filter=nonvariant, distinct=True),
        _export_year_min=Min("entities__models__year", filter=nonvariant),
        _export_year_max=Max("entities__models__year", filter=nonvariant),
    )
    return annotated


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _register(spec: ExportSpec) -> None:
    model = spec.model
    entity_type_plural = model.entity_type_plural
    schema = _build_schema(spec)
    adapter: TypeAdapter[Any] = TypeAdapter(list[schema])  # type: ignore[valid-type]
    cache_base = model.entity_type

    def _view(request: HttpRequest) -> HttpResponse:
        check_and_record_ip(request, _export_rate_limit_spec())
        key = export_key(cache_base)
        cached = get_cached_response(key)
        if cached is not None:
            return cached
        min_rank = get_minimum_display_rank()
        sfl_map = build_source_field_license_map()
        id_only_re = _id_only_link_re()  # once per build, honoring is_enabled toggles
        objs = list(_build_qs(spec))
        link_map = _build_link_map([o.description for o in objs])
        rows = [
            _serialize_row(
                obj,
                spec,
                min_rank=min_rank,
                sfl_map=sfl_map,
                link_map=link_map,
                id_only_re=id_only_re,
            )
            for obj in objs
        ]
        return set_cached_response(key, adapter, rows)

    label_plural = entity_type_plural.replace("-", " ").title()
    _view.__name__ = f"export_{entity_type_plural.replace('-', '_')}"
    export_router.get(
        f"/{entity_type_plural}/",
        # 429 documented so the public OpenAPI advertises the per-IP limit and
        # its Retry-After body (the export API is the sole documented surface).
        response={200: list[schema], 429: RateLimitErrorSchema},  # type: ignore[valid-type]
        summary=label_plural,
        description=f"Bulk export all {label_plural}.",
    )(_view)


_REGISTRY = _build_registry()
EXPORT_ENTITY_TYPES: tuple[str, ...] = tuple(
    sorted(spec.model.entity_type for spec in _REGISTRY.values())
)

for _spec in _REGISTRY.values():
    _register(_spec)
