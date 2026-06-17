"""Locations router — browse manufacturers by geography."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple, cast

from django.core.cache import cache
from django.db.models import Count, F, Prefetch, Q
from django.http import HttpRequest
from django.utils import timezone
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.provenance.helpers import claims_prefetch
from apps.provenance.schemas import RichTextSchema

from ..cache import locations_tree_key
from ..models import (
    CorporateEntity,
    CorporateEntityLocation,
    Location,
    MachineModel,
    Manufacturer,
)
from ..services.location_paths import lookup_child_division
from ._typing import HasModelCount
from .images import first_thumbnail
from .rich_text import describe
from .schemas import CatalogDetailSchema

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LocationManufacturerSchema(Schema):
    name: str
    public_id: str
    model_count: int = 0
    thumbnail_url: str | None = None


class LocationChildRef(Schema):
    name: str
    public_id: str
    location_type: str
    manufacturer_count: int = 0


class LocationAncestorRef(Schema):
    name: str
    public_id: str


class LocationDetailSchema(CatalogDetailSchema):
    slug: str
    location_type: str | None = None
    # Server-derived label for the next tier of children (e.g. "state",
    # "city"). ``None`` when divisions are missing or exhausted; the
    # frontend uses this to suppress the "+ New …" action rather than
    # show a wrong label.
    expected_child_type: str | None = None
    short_name: str | None = None
    code: str | None = None
    divisions: list[str] | None = None
    aliases: list[str] = []
    manufacturer_count: int = 0
    ancestors: list[LocationAncestorRef] = []
    children: list[LocationChildRef] = []
    manufacturers: list[LocationManufacturerSchema] = []


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _LocationNode:
    """Internal tree node; `manufacturer_pks` is plumbing — do not serialize."""

    name: str
    slug: str
    location_path: str
    location_type: str
    parent_path: str | None
    manufacturer_pks: frozenset[int]
    short_name: str
    code: str
    aliases: tuple[str, ...]
    # Freshness for JSON-LD ``dateModified`` / sitemap ``<lastmod>``; sourced
    # from ``Location.last_modified`` (== ``updated_at``, Location doesn't
    # widen) at cache-build time so detail reads stay zero-query.
    last_modified: datetime
    # Pre-rendered at cache-build time so public detail reads stay
    # zero-query. Description rendering has no rank dependency
    # (``build_rich_text`` only consults claims for attribution; rank
    # gating in this module is image-only and runs per-request via
    # ``_get_manufacturers_for_pks``), so caching the rendered schema
    # is safe.
    description: RichTextSchema
    # Country rows declare a list of division-level labels (e.g.
    # ``("state", "city")``); empty tuple on non-country rows. Cached
    # alongside the rest of the tree so the detail serializer can
    # derive ``expected_child_type`` without a per-request DB hit.
    divisions: tuple[str, ...] = ()


class _LocationTree(NamedTuple):
    """Cached location tree: node lookup plus parent-keyed child index."""

    nodes: dict[str, _LocationNode]
    children_index: dict[str | None, list[str]]


def _get_location_tree() -> _LocationTree:
    """Build location data from Location + CorporateEntityLocation records.

    Results are cached; invalidated by ``invalidate_all()``.
    """
    result = cache.get(locations_tree_key())
    if result is not None:
        return cast(_LocationTree, result)

    # Load all locations with parent chains (up to 4 levels deep).
    # ``aliases`` + ``claims_prefetch()`` feed ``build_rich_text`` so
    # the rendered description can be cached per node.
    all_locs = list(
        Location.objects.active()
        .select_related("parent__parent__parent__parent")
        .prefetch_related("aliases", claims_prefetch())
        .all()
    )

    # Accumulate manufacturer PKs at each location and all its ancestors.
    mfr_pks_by_path: dict[str, set[int]] = {}
    for cel in (
        CorporateEntityLocation.objects.select_related(
            "location__parent__parent__parent__parent",
            "corporate_entity__manufacturer",
        )
        .filter(corporate_entity__manufacturer__isnull=False)
        .filter(active_status_q("corporate_entity"))
    ):
        mfr_pk = cel.corporate_entity.manufacturer_id
        cur: Location | None = cel.location
        while cur is not None:
            mfr_pks_by_path.setdefault(cur.location_path, set()).add(mfr_pk)
            cur = cur.parent

    nodes: dict[str, _LocationNode] = {}
    children_index: dict[str | None, list[str]] = {}
    for loc in all_locs:
        parent_path = loc.parent.location_path if loc.parent else None
        nodes[loc.location_path] = _LocationNode(
            name=loc.name,
            slug=loc.slug,
            location_path=loc.location_path,
            location_type=loc.location_type,
            parent_path=parent_path,
            manufacturer_pks=frozenset(mfr_pks_by_path.get(loc.location_path, set())),
            short_name=loc.short_name,
            code=loc.code,
            aliases=tuple(a.value for a in loc.aliases.all()),
            description=describe(loc),
            divisions=tuple(loc.divisions or ()),
            last_modified=loc.last_modified,
        )
        children_index.setdefault(parent_path, []).append(loc.location_path)

    tree = _LocationTree(nodes, children_index)
    cache.set(locations_tree_key(), tree, timeout=None)
    return tree


def _children_of(
    path: str | None,
    nodes: dict[str, _LocationNode],
    children_index: dict[str | None, list[str]],
) -> list[_LocationNode]:
    """Return child nodes sorted by manufacturer_count desc, then name."""
    return sorted(
        [nodes[p] for p in children_index.get(path, []) if p in nodes],
        key=lambda n: (-len(n.manufacturer_pks), n.name),
    )


def _ancestors_of(path: str, nodes: dict[str, _LocationNode]) -> list[_LocationNode]:
    """Return ancestor chain from root to immediate parent (root first)."""
    ancestors: list[_LocationNode] = []
    node = nodes.get(path)
    if node is None:
        return ancestors
    parent_path = node.parent_path
    while parent_path is not None:
        parent = nodes.get(parent_path)
        if parent is None:
            break
        ancestors.insert(0, parent)
        parent_path = parent.parent_path
    return ancestors


def _to_child_ref(node: _LocationNode) -> LocationChildRef:
    return LocationChildRef(
        name=node.name,
        public_id=node.location_path,
        location_type=node.location_type,
        manufacturer_count=len(node.manufacturer_pks),
    )


def _get_manufacturers_for_pks(pks: Iterable[int]) -> list[LocationManufacturerSchema]:
    """Return serialized manufacturer list for a set of PKs."""
    qs = (
        Manufacturer.objects.active()
        .filter(pk__in=pks)
        .annotate(
            model_count=Count(
                "entities__models",
                filter=Q(entities__models__variant_of__isnull=True)
                & active_status_q("entities__models"),
            )
        )
        .prefetch_related(
            Prefetch(
                "entities",
                queryset=CorporateEntity.objects.active().prefetch_related(
                    Prefetch(
                        "models",
                        queryset=MachineModel.objects.active()
                        .filter(variant_of__isnull=True)
                        .order_by(F("year").desc(nulls_last=True))
                        .only("corporate_entity_id", "extra_data"),
                    ),
                ),
            ),
        )
        .order_by("-model_count", "name")
    )

    min_rank = get_minimum_display_rank()
    return [
        LocationManufacturerSchema(
            name=mfr.name,
            public_id=mfr.public_id,
            model_count=cast(HasModelCount, mfr).model_count,
            thumbnail_url=first_thumbnail(mfr.entities.all(), min_rank=min_rank),
        )
        for mfr in qs
    ]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

locations_router = Router(tags=["private"])


def _get_location_detail(location_path: str) -> LocationDetailSchema:
    """Shared implementation for all location detail endpoints.

    Empty ``location_path`` returns the global root view: all countries as
    children, all manufacturers (across every country) as the main payload.
    """
    nodes, children_index = _get_location_tree()

    if location_path == "":
        children = _children_of(None, nodes, children_index)
        global_pks: frozenset[int] = frozenset().union(
            *(n.manufacturer_pks for n in children)
        )
        return LocationDetailSchema(
            name="",
            public_id="",
            # Synthetic root (the /locations listing, not a real entity):
            # freshness is the newest location in the tree, falling back to
            # now when the catalog has no locations yet.
            last_modified=max(
                (n.last_modified for n in nodes.values()),
                default=timezone.now(),
            ),
            slug="",
            location_type=None,
            # Top-level "+ New …" creates a country; the form has its
            # own divisions input so no derivation is needed here.
            expected_child_type="country",
            manufacturer_count=len(global_pks),
            ancestors=[],
            children=[_to_child_ref(c) for c in children],
            manufacturers=_get_manufacturers_for_pks(global_pks),
        )

    node = nodes.get(location_path)
    if not node:
        raise HttpError(404, "Location not found")

    ancestors = _ancestors_of(location_path, nodes)
    children = _children_of(location_path, nodes, children_index)

    # Country ancestor is at the root of the ancestor chain; for country
    # rows it's the node itself. ``divisions`` lives only on country
    # rows, so we read it from there.
    country = ancestors[0] if ancestors else node
    expected_child_type = lookup_child_division(
        country.divisions, location_path.count("/")
    )

    return LocationDetailSchema(
        name=node.name,
        public_id=location_path,
        last_modified=node.last_modified,
        slug=node.slug,
        location_type=node.location_type,
        expected_child_type=expected_child_type,
        description=node.description,
        short_name=node.short_name or None,
        code=node.code or None,
        divisions=list(node.divisions) if node.divisions else None,
        aliases=list(node.aliases),
        manufacturer_count=len(node.manufacturer_pks),
        ancestors=[
            LocationAncestorRef(name=a.name, public_id=a.location_path)
            for a in ancestors
        ],
        children=[_to_child_ref(c) for c in children],
        manufacturers=_get_manufacturers_for_pks(node.manufacturer_pks),
    )


# Two routes only: ``/`` for the global root (no segments) and
# ``/{path:location_path}`` for any concrete location. Ninja's
# ``{path:...}`` converter accepts slashes, so a single non-empty route
# covers every supported depth — same pattern used by the page-endpoints
# router and the new write/delete-restore routes. Pindata's max depth is
# 4 today; this code does not enforce depth (the 422 / 404 falls out of
# the cached tree lookup).


@locations_router.get("/", response=LocationDetailSchema)
@decorate_view(cache_control(no_cache=True))
def get_location_root(request: HttpRequest) -> LocationDetailSchema:
    """Return the global root: all countries as children, all manufacturers."""
    return _get_location_detail("")


@locations_router.get("/{path:location_path}", response=LocationDetailSchema)
@decorate_view(cache_control(no_cache=True))
def get_location_detail(
    request: HttpRequest, location_path: str
) -> LocationDetailSchema:
    """Return detail for any concrete location (1–N segments)."""
    return _get_location_detail(location_path)
