"""YAML data-patch adapter: parse a patch file into an ``IngestPlan``.

A *data patch* is a small, source-attributed set of catalog claims authored
as plain YAML and applied through the existing ingest apply engine
(:mod:`apps.catalog.ingestion.apply`) — not a parallel engine. This module
turns a patch's text into an :class:`IngestPlan`; the ``ingest_patches``
command discovers, hashes, ledger-checks and applies them.

See ``docs/DataPatches.md`` for the file format and design rationale.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NamedTuple, cast
from urllib.parse import urlparse

import yaml
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.api.soft_delete import plan_soft_delete
from apps.catalog.claims import build_relationship_claim, get_relationship_namespaces
from apps.catalog.ingestion.apply import (
    CitationRef,
    IngestPlan,
    PlannedClaimAssert,
    PlannedClaimRetract,
    PlannedEntityCreate,
    PreWriteHook,
    RunReport,
)
from apps.catalog.models import CatalogModel
from apps.catalog.resolve import resolve_relationships_bulk
from apps.citation.extractors import EXTRACTORS
from apps.citation.models import (
    CITATION_SOURCE_IDENTIFIER_MAX_LENGTH,
    CITATION_SOURCE_LINK_URL_MAX_LENGTH,
)
from apps.citation.seed_data.types import SeedLink, SeedSource
from apps.citation.seeding import ensure_root_source, validate_root_source
from apps.core.entity_types import get_linkable_model
from apps.core.types import EntityKey, JsonBody
from apps.provenance.models import Claim, Source, get_claim_fields
from apps.provenance.models.changeset import CHANGESET_NOTE_MAX_LENGTH
from apps.provenance.validation import get_relationship_schema

PATCH_ID_RE = re.compile(r"^\d{4}-[a-z0-9-]+$")

# Keys in a claim entry's value mapping that are directives, not claim fields.
RESERVED_FIELD_KEYS = frozenset(
    {"create", "delete", "expect", "retract", "remove", "note", "cite"}
)

# The claim-controlled lifecycle field (``LifecycleStatusModel.status``).
# Patches never write it directly — it's created as ``active`` and soft-deleted
# to ``deleted`` via the ``delete:`` directive, which routes through the
# soft-delete planner. A raw claim would skip that planner's safety checks.
LIFECYCLE_STATUS_FIELD = "status"

# Allowed keys in a `sources:` node / its links, derived from the seed TypedDicts
# (the single source of truth). `children` is excluded — v1 sources are flat.
ALLOWED_SOURCE_KEYS = frozenset(SeedSource.__annotations__) - {"children"}
ALLOWED_LINK_KEYS = frozenset(SeedLink.__annotations__)


class PatchError(Exception):
    """A patch is malformed, unresolvable, or violates a guard.

    Raised before any write. The command turns it into a failed-run report.
    """


# ---------------------------------------------------------------------------
# Strict YAML loader
# ---------------------------------------------------------------------------


class _StrictPatchLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys and YAML implicit type coercion.

    * Duplicate mapping keys raise (``safe_load`` silently keeps the last,
      which would drop a claim and skew the content hash).
    * Implicit resolvers are restricted to JSON-shaped scalars, so a bare
      ``1996-01-01`` stays a string and ``no`` stays ``"no"`` — JSON
      semantics, no YAML 1.1 surprises.
    """


def _construct_mapping_no_duplicates(
    loader: _StrictPatchLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    # Keys are deliberately ``object``, not ``str``: at construct time a YAML
    # key may still resolve to a non-string scalar (``1996:`` → int). The
    # JSON contract (string keys, JSON-shaped values) is enforced separately
    # by ``_assert_json`` after the document is built.
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)  # type: ignore[no-untyped-call]
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)  # type: ignore[no-untyped-call]
    return mapping


_StrictPatchLoader.add_constructor(
    "tag:yaml.org,2002:map", _construct_mapping_no_duplicates
)

# Reset implicit resolvers to JSON-shaped scalars only (bool=true/false,
# null, int, float). Everything else — dates, yes/no/on/off — stays a string.
_StrictPatchLoader.yaml_implicit_resolvers = {}
_JSON_RESOLVERS: list[tuple[str, re.Pattern[str], str]] = [
    ("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), "tf"),
    ("tag:yaml.org,2002:null", re.compile(r"^(?:null|~)$"), "n~"),
    ("tag:yaml.org,2002:int", re.compile(r"^[-+]?[0-9]+$"), "-+0123456789"),
    (
        "tag:yaml.org,2002:float",
        re.compile(r"^[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?$"),
        "-+.0123456789",
    ),
]
for _tag, _pattern, _first_chars in _JSON_RESOLVERS:
    for _ch in _first_chars:
        _StrictPatchLoader.add_implicit_resolver(_tag, _pattern, _ch)  # type: ignore[no-untyped-call]


def _assert_json(value: object, path: str = "<root>") -> None:
    """Reject any non-JSON value that slipped through (e.g. an explicit tag)."""
    if value is None or isinstance(value, str | int | bool):
        return
    if isinstance(value, float):
        # NaN / Infinity (e.g. via ``!!float .nan``) are not valid JSON.
        if not math.isfinite(value):
            raise PatchError(f"non-finite float at {path}: {value!r} (not valid JSON)")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _assert_json(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PatchError(f"non-string mapping key at {path}: {key!r}")
            _assert_json(item, f"{path}.{key}")
        return
    raise PatchError(
        f"non-JSON value at {path}: {type(value).__name__} "
        f"(quote it to keep it a string)"
    )


def parse_patch_text(text: str) -> JsonBody:
    """Parse patch YAML into a plain JSON-shaped dict, strictly."""
    try:
        data = yaml.load(text, Loader=_StrictPatchLoader)  # noqa: S506 - strict subclass
    except yaml.YAMLError as exc:
        raise PatchError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PatchError("patch root must be a mapping")
    _assert_json(data)
    return data


def fingerprint(data: JsonBody) -> str:
    """sha256 of the normalised parsed content (canonical JSON).

    Stable to comment/whitespace/key-order changes; sensitive to claim
    order and values — so a cosmetic reformat doesn't trip immutability but
    a semantic change does.
    """
    canonical = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,  # backstop: non-finite is already rejected by _assert_json
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Parsed patch document
# ---------------------------------------------------------------------------


# A ``remove:`` directive's shape: relationship namespace → member public_ids
# to drop. (Both keys and members are bare ``str`` — namespace and public_id
# are uniformly untyped strings across the catalog; this alias names the
# structure without pretending to enforce them.)
type RelationshipMembers = dict[str, list[str]]


@dataclass(frozen=True, kw_only=True)
class _PatchEntry:
    """Common to every claim entry: the entity reference and provenance.

    Subclassed by the three entry kinds — :class:`CreateEntry`,
    :class:`EditEntry`, :class:`DeleteEntry`. The kind is decided while
    parsing, from the ``create:``/``delete:`` directives, and each subclass
    carries *only* the fields legal for that kind. So an illegal combination
    (``expect`` on a create, ``retract`` on a delete, a field assertion on a
    delete, …) is a parse-time error rather than a runtime flag check, and
    ``build_plan`` dispatches on the entry's *type* instead of re-testing
    boolean combinations.
    """

    entity_type: str
    public_id: str
    # Per-entry provenance, common to all kinds. ``note`` becomes the entity's
    # ChangeSet note; ``cite`` is a raw ``scheme:identifier`` string or a
    # ``http(s)://`` URL, parsed + validated into a CitationRef in build_plan.
    # Empty when unset.
    note: str = ""
    cite: str = ""

    @property
    def ref(self) -> str:
        return f"{self.entity_type}.{self.public_id}"


@dataclass(frozen=True, kw_only=True)
class CreateEntry(_PatchEntry):
    """Create a new entity and assert its authored fields (``create: true``)."""

    fields: JsonBody


@dataclass(frozen=True, kw_only=True)
class EditEntry(_PatchEntry):
    """Assert/supersede, retract and/or remove on an existing entity.

    The default kind — an entry with neither ``create:`` nor ``delete:``.
    """

    expect: JsonBody
    # Scalar/FK field names whose claim from this source to deactivate.
    retract: list[str]
    # The relationship analogue of ``retract``, by a *different* mechanism: a map
    # of relationship namespace → member public_ids to drop by superseding each
    # with an ``exists=false`` tombstone (the claim stays active, resolving to
    # "absent") — exactly how the in-app editor drops a member.
    remove: RelationshipMembers
    fields: JsonBody


@dataclass(frozen=True, kw_only=True)
class DeleteEntry(_PatchEntry):
    """Soft-delete an existing entity (``delete: true``).

    Carries an optional ``expect:`` drift guard and provenance only — no field
    assertions, ``retract`` or ``remove`` (reassign any references in an
    earlier patch, before the delete).
    """

    expect: JsonBody


# A parsed claim entry, discriminated by kind.
type PatchEntry = CreateEntry | EditEntry | DeleteEntry


@dataclass(frozen=True)
class PatchDoc:
    """A fully-parsed, structurally-valid patch (no DB access yet)."""

    attribution: str
    description: str
    claims: list[PatchEntry]
    fingerprint: str
    # Non-claim citation-source upserts (the `sources:` block). Empty for a
    # claims-only patch. Shape-validated here; field-validated in build_plan.
    sources: list[SeedSource] = field(default_factory=list)


def _parse_link_shape(link: object, where: str) -> None:
    """Validate one `sources:` link mapping's shape (not its field values)."""
    if not isinstance(link, dict):
        raise PatchError(f"{where} must be a mapping")
    unknown = set(link) - ALLOWED_LINK_KEYS
    if unknown:
        raise PatchError(f"{where}: unknown key(s) {sorted(unknown)}")
    for key in ("url", "link_type"):
        value = link.get(key)
        if not isinstance(value, str) or not value:
            raise PatchError(f"{where}: {key!r} is required and must be a string")
    if not isinstance(link.get("label", ""), str):
        raise PatchError(f"{where}: 'label' must be a string")


def _parse_source_node(entry: object, where: str) -> SeedSource:
    """Validate one `sources:` node's shape and return it as a SeedSource.

    Shape only — required keys, no unknown keys, `children` rejected (v1 is
    flat), link mappings well-formed. Field *values* (enum, ranges, URL format)
    are validated against the model in build_plan's read phase.
    """
    if not isinstance(entry, dict):
        raise PatchError(f"{where} must be a mapping")
    if "children" in entry:
        raise PatchError(
            f"{where}: nested 'children' is unsupported — v1 `sources:` is flat "
            f"(create child sources via 'cite:' instead)"
        )
    unknown = set(entry) - ALLOWED_SOURCE_KEYS
    if unknown:
        raise PatchError(f"{where}: unknown key(s) {sorted(unknown)}")
    for key in ("name", "source_type"):
        value = entry.get(key)
        if not isinstance(value, str) or not value:
            raise PatchError(f"{where}: {key!r} is required and must be a string")
    raw_links = entry.get("links", [])
    if not isinstance(raw_links, list):
        raise PatchError(f"{where}: 'links' must be a list")
    for j, link in enumerate(raw_links):
        _parse_link_shape(link, f"{where}.links[{j}]")
    # Shape-validated above; narrow the JSON dict to the seed TypedDict.
    return cast(SeedSource, entry)


def _require_bool(raw_fields: JsonBody, key: str, ref: str) -> bool:
    raw = raw_fields.get(key, False)
    if not isinstance(raw, bool):
        raise PatchError(f"{ref}: {key!r} must be a boolean")
    return raw


def _require_str(raw_fields: JsonBody, key: str, ref: str) -> str:
    raw = raw_fields.get(key, "")
    if not isinstance(raw, str):
        raise PatchError(f"{ref}: {key!r} must be a string")
    return raw


def _parse_expect(raw_fields: JsonBody, ref: str) -> JsonBody:
    raw = raw_fields.get("expect", {})
    if not isinstance(raw, dict):
        raise PatchError(f"{ref}: 'expect' must be a mapping")
    return cast(JsonBody, raw)


def _parse_retract(raw_fields: JsonBody, ref: str) -> list[str]:
    raw = raw_fields.get("retract", [])
    if not isinstance(raw, list) or not all(isinstance(f, str) for f in raw):
        raise PatchError(f"{ref}: 'retract' must be a list of field names")
    return cast(list[str], raw)


def _parse_remove(raw_fields: JsonBody, ref: str) -> RelationshipMembers:
    raw = raw_fields.get("remove", {})
    if not isinstance(raw, dict) or not all(
        isinstance(namespace, str)
        and isinstance(members, list)
        and all(isinstance(m, str) for m in members)
        for namespace, members in raw.items()
    ):
        raise PatchError(
            f"{ref}: 'remove' must be a mapping of relationship namespace to a "
            f"list of member public_ids (e.g. {{location: [germany]}})"
        )
    return cast(RelationshipMembers, raw)


def _parse_entry(raw_entry: object, index: int) -> PatchEntry:
    """Parse + structurally validate one ``claims:`` entry into a typed kind.

    Decides the entry kind from ``create:``/``delete:`` and validates that the
    entry carries only the directives legal for that kind — so an illegal
    combination is rejected here, at parse time, rather than by flag checks in
    ``build_plan``. Field *values* and DB resolution stay in ``build_plan``.
    """
    if not isinstance(raw_entry, dict) or len(raw_entry) != 1:
        raise PatchError(
            f"claims[{index}] must be a single-key mapping (entity ref → fields)"
        )
    ((ref, raw_fields),) = raw_entry.items()
    if not isinstance(ref, str) or "." not in ref:
        raise PatchError(f"claims[{index}] key {ref!r} must be 'type.public_id'")
    entity_type, public_id = ref.split(".", 1)
    if not entity_type or not public_id:
        raise PatchError(f"claims[{index}] key {ref!r} must be 'type.public_id'")
    if not isinstance(raw_fields, dict):
        raise PatchError(f"claims[{index}] ({ref}) value must be a mapping")

    create = _require_bool(raw_fields, "create", ref)
    delete = _require_bool(raw_fields, "delete", ref)
    note = _require_str(raw_fields, "note", ref)
    raw_cite = raw_fields.get("cite", "")
    if not isinstance(raw_cite, str):
        raise PatchError(f"{ref}: 'cite' must be a 'scheme:identifier' or URL string")
    # Authored claim fields: everything that isn't a reserved directive key.
    fields = {k: v for k, v in raw_fields.items() if k not in RESERVED_FIELD_KEYS}
    common = {
        "entity_type": entity_type,
        "public_id": public_id,
        "note": note,
        "cite": raw_cite,
    }

    if create and delete:
        raise PatchError(f"{ref}: 'create' and 'delete' are mutually exclusive")

    if delete:
        for key in ("retract", "remove"):
            if key in raw_fields:
                raise PatchError(f"{ref}: {key!r} and 'delete' are mutually exclusive")
        if fields:
            raise PatchError(
                f"{ref}: a delete entry takes no field assertions "
                f"({', '.join(sorted(fields))}) — reassign references in a "
                f"separate entry, in an earlier patch, before the delete"
            )
        return DeleteEntry(**common, expect=_parse_expect(raw_fields, ref))

    if create:
        for key in ("expect", "retract", "remove"):
            if key in raw_fields:
                raise PatchError(f"{ref}: {key!r} is meaningless on a create")
        return CreateEntry(**common, fields=fields)

    return EditEntry(
        **common,
        expect=_parse_expect(raw_fields, ref),
        retract=_parse_retract(raw_fields, ref),
        remove=_parse_remove(raw_fields, ref),
        fields=fields,
    )


def load_patch(text: str) -> PatchDoc:
    """Parse + structurally validate patch text. Raises :class:`PatchError`."""
    data = parse_patch_text(text)
    fp = fingerprint(data)

    attribution = data.get("attribution")
    if not isinstance(attribution, str) or not attribution:
        raise PatchError("'attribution' is required and must be a Source slug")

    description = data.get("description", "")
    if not isinstance(description, str):
        raise PatchError("'description' must be a string")

    raw_claims = data.get("claims", [])
    if not isinstance(raw_claims, list):
        raise PatchError("'claims' must be a list")
    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raise PatchError("'sources' must be a list")
    if not raw_claims and not raw_sources:
        raise PatchError("a patch must carry a non-empty 'claims' or 'sources'")

    sources = [
        _parse_source_node(entry, f"sources[{i}]")
        for i, entry in enumerate(raw_sources)
    ]

    claims = [_parse_entry(entry, i) for i, entry in enumerate(raw_claims)]

    return PatchDoc(
        attribution=attribution,
        description=description,
        claims=claims,
        fingerprint=fp,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Adapter: PatchDoc → IngestPlan
# ---------------------------------------------------------------------------


class _Target(NamedTuple):
    """Where a claim assertion lands: an existing entity or a planned handle."""

    content_type_id: int | None = None
    object_id: int | None = None
    handle: str | None = None


class _TargetContribution(NamedTuple):
    """One entry's contribution to the plan-wide guards for one existing entity.

    A create contributes nothing (it targets a handle, not an existing entity);
    a delete contributes one of these per soft-deleted entity (root + cascade)
    with empty field sets; an edit contributes one carrying its retract / assert
    / remove sets. ``_validate_plan_wide`` merges these across entries.
    """

    ref: str
    has_provenance: bool
    retracted_fields: frozenset[str]
    asserted_fields: frozenset[str]
    asserted_members: frozenset[str]
    # claim_key → "namespace public_id" label, for the assert/remove clash error.
    removed_members: dict[str, str]


class _EntryResult(NamedTuple):
    """What ``_process_entry`` hands back for the cross-entry validation passes.

    The plan mutations (entities, assertions, retractions, warnings) have already
    happened inside ``_process_entry``; this carries only what the plan-wide
    guards need. ``matched`` counts toward ``records_matched`` (edit/delete yes,
    create no).
    """

    matched: bool
    contributions: dict[EntityKey, _TargetContribution]


class _RemovalResult(NamedTuple):
    """Outcome of ``_add_removals`` for one entry.

    ``removed_members`` is every *intended* removal (claim_key → label), recorded
    for the clash guard regardless of DB state; ``carrier_written`` is whether at
    least one tombstone was actually emitted (a no-op removal writes nothing).
    """

    removed_members: dict[str, str]
    carrier_written: bool


def _parse_provenance(entry: PatchEntry) -> tuple[str, CitationRef | None]:
    """Validate an entry's ``note``/``cite`` and parse ``cite`` into a CitationRef.

    Length-checks each value against the DB column it lands in so an overlong
    value fails as a clear :class:`PatchError` here rather than deep in
    persistence. ``cite`` is one of two forms:

    * ``scheme:identifier`` — the scheme must be a known extractor and the
      identifier must normalize (``ipdb:4443``).
    * a ``http(s)://`` URL — a standalone web source. A URL that matches a
      known scheme's record pattern is rejected: cite it as ``scheme:identifier``
      so it dedups through the scheme path.
    """
    note = entry.note
    if len(note) > CHANGESET_NOTE_MAX_LENGTH:
        raise PatchError(
            f"{entry.ref}: note exceeds {CHANGESET_NOTE_MAX_LENGTH} characters"
        )
    if not entry.cite:
        return note, None
    if entry.cite.startswith(("http://", "https://")):
        return note, _parse_cite_url(entry)
    scheme, sep, raw_id = entry.cite.partition(":")
    if not sep or not scheme or not raw_id:
        raise PatchError(
            f"{entry.ref}: cite {entry.cite!r} must be 'scheme:identifier' (e.g. 'ipdb:4443')"
        )
    extractor = EXTRACTORS.get(scheme)
    if extractor is None:
        raise PatchError(
            f"{entry.ref}: unknown cite scheme {scheme!r} "
            f"(known: {', '.join(sorted(EXTRACTORS))})"
        )
    normalized = extractor.normalize(raw_id)
    if normalized is None:
        raise PatchError(f"{entry.ref}: invalid {scheme} identifier {raw_id!r}")
    if len(normalized) > CITATION_SOURCE_IDENTIFIER_MAX_LENGTH:
        raise PatchError(
            f"{entry.ref}: cite identifier exceeds "
            f"{CITATION_SOURCE_IDENTIFIER_MAX_LENGTH} characters"
        )
    return note, CitationRef(scheme=scheme, identifier=normalized)


def _parse_cite_url(entry: PatchEntry) -> CitationRef:
    """Validate a ``http(s)://`` ``cite`` URL into a standalone-web CitationRef.

    Rejects a URL that matches a known scheme's record pattern (it has a
    canonical ``scheme:identifier`` form that dedups correctly), a malformed
    URL, and one too long for the link column.
    """
    url = entry.cite
    for scheme, extractor in EXTRACTORS.items():
        identifier = extractor.extract(url)
        if identifier is not None:
            raise PatchError(
                f"{entry.ref}: cite URL matches the {scheme} scheme — "
                f"cite it as {scheme}:{identifier} instead"
            )
    # The caller guarantees an http(s):// scheme, so a host is all that's left
    # to validate (``https://`` alone has none).
    if not urlparse(url).hostname:
        raise PatchError(f"{entry.ref}: cite {url!r} is not a valid URL")
    if len(url) > CITATION_SOURCE_LINK_URL_MAX_LENGTH:
        raise PatchError(
            f"{entry.ref}: cite URL exceeds {CITATION_SOURCE_LINK_URL_MAX_LENGTH} "
            f"characters"
        )
    return CitationRef(url=url)


def build_plan(doc: PatchDoc, *, source: Source, patch_id: str) -> IngestPlan:
    """Compile a parsed patch into an :class:`IngestPlan`.

    Drives the two-phase compile: ``_process_entry`` resolves, validates and
    emits each entry (all DB reads + plan mutations happen there, in order),
    returning an :class:`_EntryResult`; ``_validate_plan_wide`` then runs the
    cross-entry guards over the collected results. ``apply_plan(plan)`` does the
    writing.
    """
    plan = IngestPlan(
        source=source,
        input_fingerprint=doc.fingerprint,
        patch_id=patch_id,
        note=doc.description,
        records_parsed=len(doc.claims),
    )
    rel_namespaces = get_relationship_namespaces()
    rel_fields_by_model: dict[type[CatalogModel], set[str]] = defaultdict(set)
    # Refs already created in this patch. A second create for the same ref would
    # mint a duplicate handle and blow up as a ValueError deep in the apply layer
    # (which the command doesn't catch); reject it cleanly in _process_entry.
    created_refs: set[str] = set()

    results = [
        _process_entry(
            plan,
            entry,
            source=source,
            rel_namespaces=rel_namespaces,
            rel_fields_by_model=rel_fields_by_model,
            created_refs=created_refs,
        )
        for entry in doc.claims
    ]
    plan.records_matched = sum(r.matched for r in results)
    _validate_plan_wide(results)

    # Relationship resolution: delegate to the canonical post-mutation
    # dispatch (model-driven; no hand-maintained namespace→resolver map). The
    # engine resolves scalar/FK itself; these hooks cover the relationships.
    for rel_model, field_names in rel_fields_by_model.items():
        rel_ct_id = ContentType.objects.get_for_model(rel_model).pk
        plan.resolve_hooks.setdefault(rel_ct_id, []).append(
            _make_resolve_hook(rel_model, sorted(field_names))
        )

    _plan_citation_sources(plan, doc.sources)

    return plan


def _process_entry(
    plan: IngestPlan,
    entry: PatchEntry,
    *,
    source: Source,
    rel_namespaces: frozenset[str],
    rel_fields_by_model: dict[type[CatalogModel], set[str]],
    created_refs: set[str],
) -> _EntryResult:
    """Resolve, validate and emit one claim entry; return its cross-entry contribution.

    All DB reads and plan mutations for the entry happen here. The entry kind is
    its parsed type — the illegal directive combinations were already rejected in
    ``_parse_entry``, so each branch only does its own DB-dependent work. The
    per-entry provenance-carrier check is enforced inline; the returned
    :class:`_EntryResult` carries only what ``_validate_plan_wide`` needs.
    """
    note, citation_ref = _parse_provenance(entry)
    model_class = _resolve_model_class(entry)
    ct_id = ContentType.objects.get_for_model(model_class).pk
    existing = _lookup_entity(model_class, entry.public_id)
    has_provenance = bool(note) or citation_ref is not None

    # A delete carries no field assertions and no relationship work, so it
    # finishes here, registering every soft-deleted entity (root + cascade) with
    # the same-entity guard: each carries the entry's note/cite on its
    # status=deleted claim, so a separate entry on any of them that also carries
    # provenance is a genuine collision.
    if isinstance(entry, DeleteEntry):
        if existing is None:
            raise PatchError(f"{entry.ref}: no such {entry.entity_type} to delete")
        _check_expect(model_class, existing, entry)
        affected = _add_delete(
            plan, existing, entry, note=note, citation_ref=citation_ref
        )
        contributions = {
            tkey: _TargetContribution(
                ref=entry.ref,
                has_provenance=has_provenance,
                retracted_fields=frozenset(),
                asserted_fields=frozenset(),
                asserted_members=frozenset(),
                removed_members={},
            )
            for tkey in affected
        }
        return _EntryResult(matched=True, contributions=contributions)

    target: _Target
    retracted_any = False  # set by the edit branch; a real retraction carries a note
    if isinstance(entry, CreateEntry):
        if existing is not None:
            raise PatchError(
                f"{entry.ref}: create:true but a {entry.entity_type} with this "
                f"public_id already exists"
            )
        if entry.ref in created_refs:
            raise PatchError(f"{entry.ref}: duplicate create entry in this patch")
        created_refs.add(entry.ref)
        _add_create(plan, model_class, entry, entry.ref, note=note)
        target = _Target(handle=entry.ref)
    else:
        if existing is None:
            raise PatchError(
                f"{entry.ref}: no such {entry.entity_type} (add create:true to create it)"
            )
        _check_expect(model_class, existing, entry)
        retracted_any = _add_retractions(
            plan, model_class, existing, entry, ct_id, source, rel_namespaces, note=note
        )
        target = _Target(content_type_id=ct_id, object_id=existing.pk)

    # Shared field loop (create + edit). Track which scalar/FK fields and which
    # relationship members were asserted on an *existing* entity — creates target
    # a handle, so object_id is None and they contribute nothing to the guards —
    # and whether any real claim carrier was written (for the provenance check).
    asserted_fields: set[str] = set()
    asserted_members: set[str] = set()
    carrier_written = False
    claim_fields = get_claim_fields(model_class)
    for key, value in entry.fields.items():
        if key == LIFECYCLE_STATUS_FIELD:
            # ``status`` is lifecycle state, not a free-form claim. Writing it
            # directly would bypass the delete planner's blocker check and
            # cascade — route lifecycle changes through the directive.
            raise PatchError(
                f"{entry.ref}: {LIFECYCLE_STATUS_FIELD!r} is lifecycle state — "
                f"soft-delete with 'delete: true', not a direct claim"
            )
        if key in claim_fields:
            _emit_direct(plan, key, value, target, note=note, citation_ref=citation_ref)
            carrier_written = True
            if target.object_id is not None:
                asserted_fields.add(key)
        elif key in rel_namespaces:
            emitted_keys = _emit_relationship(
                plan,
                model_class,
                key,
                value,
                target,
                entry,
                note=note,
                citation_ref=citation_ref,
            )
            rel_fields_by_model[model_class].add(key)
            if emitted_keys:
                carrier_written = True
            if target.object_id is not None:
                asserted_members.update(emitted_keys)
        else:
            raise PatchError(f"{entry.ref}: unknown field {key!r}")

    # Relationship-member removals (exists=false supersede). Only an EditEntry
    # carries ``remove`` (create/delete reject it at parse time).
    removed_members: dict[str, str] = {}
    if isinstance(entry, EditEntry) and entry.remove:
        assert existing is not None  # an EditEntry always matched above
        removal = _add_removals(
            plan,
            model_class,
            existing,
            entry,
            ct_id,
            source,
            rel_namespaces,
            rel_fields_by_model,
            note=note,
            citation_ref=citation_ref,
        )
        removed_members = removal.removed_members
        carrier_written = carrier_written or removal.carrier_written

    _check_provenance_carrier(
        entry,
        note=note,
        citation_ref=citation_ref,
        carrier_written=carrier_written,
        retracted_any=retracted_any,
    )

    if isinstance(entry, CreateEntry):
        # A create targets a handle, not an existing entity, so it contributes
        # nothing to the plan-wide guards and doesn't count toward records_matched.
        return _EntryResult(matched=False, contributions={})

    assert existing is not None  # an EditEntry always matched above
    contribution = _TargetContribution(
        ref=entry.ref,
        has_provenance=has_provenance,
        retracted_fields=frozenset(entry.retract),
        asserted_fields=frozenset(asserted_fields),
        asserted_members=frozenset(asserted_members),
        removed_members=removed_members,
    )
    return _EntryResult(
        matched=True, contributions={EntityKey(ct_id, existing.pk): contribution}
    )


def _check_provenance_carrier(
    entry: CreateEntry | EditEntry,
    *,
    note: str,
    citation_ref: CitationRef | None,
    carrier_written: bool,
    retracted_any: bool,
) -> None:
    """Reject a note/cite with no emitted claim to attach to (it would vanish).

    ``cite`` must ride an authored field assertion; ``note`` also rides a create's
    scaffolding claims or a real retraction. (A DeleteEntry carries its own
    ``status=deleted`` carrier and never reaches here.)

    Neither ``remove`` nor ``retract`` counts as a note carrier on its own — only
    when it actually writes something. A removal that supersedes a member emits
    an assertion (so ``carrier_written`` already covers it) and a retraction that
    deactivates a claim is reported via ``retracted_any``; a *no-op* of either
    emits nothing, so ``_persist`` makes no ChangeSet and the note would vanish.
    This keeps note in step with cite, which likewise requires a real carrier.
    """
    if citation_ref is not None and not carrier_written:
        raise PatchError(
            f"{entry.ref}: cite has no field to attach to — cite a field you're "
            f"also asserting (a retraction, a no-op removal, a field-less "
            f"create, or an empty relationship like 'tag: []' can't carry one)"
        )
    note_has_carrier = (
        carrier_written or isinstance(entry, CreateEntry) or retracted_any
    )
    if note and not note_has_carrier:
        raise PatchError(
            f"{entry.ref}: note has nothing to attach to — assert a field, "
            f"retract a currently-claimed field, create, or remove a "
            f"currently-present member (a no-op carries nothing)"
        )


def _validate_plan_wide(results: list[_EntryResult]) -> None:
    """Run the cross-entry guards over all processed entries.

    Merges each entry's per-entity contributions into accumulators — kept local
    here, so the per-entry pass stays free of cross-entry state — then enforces:

    1. one provenance-bearing entry per existing entity (their notes would
       collide in the shared ChangeSet and their cites would be ambiguous),
    2. no field both retracted and asserted on one entity by this source (the
       assert silently wins and the retract is a no-op),
    3. no relationship member both asserted present and removed on one entity
       (both write the same claim_key, so one would silently clobber the other).
    """
    entry_count: dict[EntityKey, int] = defaultdict(int)
    has_provenance: dict[EntityKey, bool] = defaultdict(bool)
    target_ref: dict[EntityKey, str] = {}
    retracted_fields: dict[EntityKey, set[str]] = defaultdict(set)
    asserted_fields: dict[EntityKey, set[str]] = defaultdict(set)
    asserted_members: dict[EntityKey, set[str]] = defaultdict(set)
    removed_members: dict[EntityKey, dict[str, str]] = defaultdict(dict)
    for result in results:
        for tkey, c in result.contributions.items():
            entry_count[tkey] += 1
            target_ref[tkey] = c.ref
            if c.has_provenance:
                has_provenance[tkey] = True
            retracted_fields[tkey] |= c.retracted_fields
            asserted_fields[tkey] |= c.asserted_fields
            asserted_members[tkey] |= c.asserted_members
            removed_members[tkey].update(c.removed_members)

    for tkey, count in entry_count.items():
        if count > 1 and has_provenance[tkey]:
            raise PatchError(
                f"{target_ref[tkey]}: multiple entries target this entity and at "
                f"least one carries note/cite — combine them into one entry "
                f"(an entity's claims share a single changeset)"
            )

    for tkey, r_fields in retracted_fields.items():
        both = sorted(r_fields & asserted_fields.get(tkey, set()))
        if both:
            raise PatchError(
                f"{target_ref[tkey]}: cannot both retract and assert "
                f"{', '.join(both)} for this entity"
            )

    for tkey, removed in removed_members.items():
        clashing = set(removed) & asserted_members.get(tkey, set())
        if clashing:
            labels = sorted(removed[claim_key] for claim_key in clashing)
            raise PatchError(
                f"{target_ref[tkey]}: cannot both assert and remove "
                f"{', '.join(labels)} for this entity"
            )


def _plan_citation_sources(plan: IngestPlan, sources: list[SeedSource]) -> None:
    """Validate `sources:` nodes (read phase) and register the upsert hook.

    Field-validates each node now — so a bad ``source_type``/date/URL fails as a
    clean :class:`PatchError` at ``--dry-run`` rather than mid-transaction — then
    appends a pre-write hook that additively get-or-creates the sources when the
    plan is applied. The upsert itself never errors on a collision (see
    ``ensure_root_source``); only author-controllable shape/value errors raise.
    """
    if not sources:
        return
    for i, node in enumerate(sources):
        try:
            validate_root_source(node)
        except ValidationError as exc:
            raise PatchError(
                f"sources[{i}] ({node['name']!r}): {_format_validation_error(exc)}"
            ) from exc
    plan.pre_write_hooks.append(_make_sources_hook(sources))


def _format_validation_error(exc: ValidationError) -> str:
    """Render a model ``ValidationError`` field-first (so the bad field is named)."""
    try:
        message_dict = exc.message_dict
    except AttributeError:
        return "; ".join(exc.messages)
    return "; ".join(
        f"{field}: {' '.join(messages)}" for field, messages in message_dict.items()
    )


def _make_sources_hook(sources: list[SeedSource]) -> PreWriteHook:
    """Build the pre-write hook that upserts a patch's citation sources.

    The closure owns the catalog-side accounting: ``ensure_root_source`` is
    source-agnostic (plain ``list[str]`` sink + a result tuple), and the hook
    folds its result into the ``RunReport`` — keeping the catalog ``RunReport``
    type out of the citation app.
    """

    def hook(report: RunReport) -> None:
        for node in sources:
            result = ensure_root_source(node, warnings=report.warnings)
            if result.source_created:
                report.sources_created += 1
            else:
                report.sources_skipped += 1
            report.source_links_created += result.links_created

    return hook


def _resolve_model_class(entry: PatchEntry) -> type[CatalogModel]:
    try:
        model_class = get_linkable_model(entry.entity_type)
    except ValueError as exc:
        raise PatchError(f"{entry.ref}: {exc}") from exc
    if not issubclass(model_class, CatalogModel):
        raise PatchError(f"{entry.ref}: {entry.entity_type!r} is not a catalog entity")
    return model_class


def _lookup_entity(
    model_class: type[CatalogModel],
    public_id: str,
) -> CatalogModel | None:
    return model_class._default_manager.filter(
        **{model_class.public_id_field: public_id}
    ).first()


def _lookup_pk(target_model: type[models.Model], public_id: str) -> int | None:
    pid_field = getattr(target_model, "public_id_field", "slug")
    return (
        target_model._default_manager.filter(**{pid_field: public_id})
        .values_list("pk", flat=True)
        .first()
    )


def _emit_assert(
    plan: IngestPlan,
    target: _Target,
    *,
    field_name: str,
    value: object = None,
    claim_key: str = "",
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> None:
    plan.assertions.append(
        PlannedClaimAssert(
            field_name=field_name,
            value=value,
            claim_key=claim_key,
            note=note,
            citation_ref=citation_ref,
            content_type_id=target.content_type_id,
            object_id=target.object_id,
            handle=target.handle,
        )
    )


def _emit_direct(
    plan: IngestPlan,
    field_name: str,
    value: object,
    target: _Target,
    *,
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> None:
    """Emit a scalar or FK claim assertion (FK value is the target public_id)."""
    _emit_assert(
        plan,
        target,
        field_name=field_name,
        value=value,
        note=note,
        citation_ref=citation_ref,
    )


class _RelationshipMemberSpec(NamedTuple):
    """The single-FK shape of a relationship namespace, for member resolution."""

    value_key: str  # the value-dict key carrying the member FK (``spec.name``)
    target_model: type[models.Model]  # what a member public_id resolves to


def _relationship_member_spec(
    model_class: type[CatalogModel],
    namespace: str,
    entry: PatchEntry,
) -> _RelationshipMemberSpec:
    """Validate *namespace* as a single-FK relationship on *model_class*.

    Shared by the assert (``_emit_relationship``) and remove (``_add_removals``)
    paths so both reject the same unsupported shapes with the same messages: an
    unknown namespace, one not valid on the subject model, or a non-single-FK
    relationship (multi-key relationships are unsupported in v1).
    """
    schema = get_relationship_schema(namespace)
    if schema is None:
        raise PatchError(f"{entry.ref}: no relationship schema for {namespace!r}")
    if model_class not in schema.valid_subjects:
        raise PatchError(
            f"{entry.ref}: relationship {namespace!r} is not valid on "
            f"{model_class.__name__}"
        )
    identity_specs = [s for s in schema.value_keys if s.identity is not None]
    if len(identity_specs) != 1 or identity_specs[0].fk_target is None:
        raise PatchError(
            f"{entry.ref}: relationship {namespace!r} is not a single-FK "
            f"relationship (unsupported in v1)"
        )
    spec = identity_specs[0]
    assert spec.fk_target is not None  # guarded above
    return _RelationshipMemberSpec(
        value_key=spec.name, target_model=spec.fk_target.model
    )


def _resolve_member_pk(
    member: object,
    namespace: str,
    rel_spec: _RelationshipMemberSpec,
    entry: PatchEntry,
) -> int:
    """Resolve one relationship member public_id to its target PK, or raise."""
    if not isinstance(member, str):
        raise PatchError(
            f"{entry.ref}: relationship {namespace!r} member {member!r} "
            f"must be a public_id string"
        )
    member_pk = _lookup_pk(rel_spec.target_model, member)
    if member_pk is None:
        raise PatchError(
            f"{entry.ref}: relationship {namespace!r} member {member!r} "
            f"does not resolve to a {rel_spec.target_model.__name__}"
        )
    return member_pk


def _emit_relationship(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    namespace: str,
    value: object,
    target: _Target,
    entry: PatchEntry,
    *,
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> list[str]:
    """Emit ``exists=true`` member assertions; return their claim_keys.

    The caller records the returned claim_keys against the target entity so the
    plan-wide assert/remove conflict guard can detect a member that is both
    asserted present and removed.
    """
    rel_spec = _relationship_member_spec(model_class, namespace, entry)
    if not isinstance(value, list):
        raise PatchError(
            f"{entry.ref}: relationship {namespace!r} value must be a list of public_ids"
        )
    emitted_keys: list[str] = []
    for member in value:
        member_pk = _resolve_member_pk(member, namespace, rel_spec, entry)
        claim_key, claim_value = build_relationship_claim(
            namespace, {rel_spec.value_key: member_pk}
        )
        _emit_assert(
            plan,
            target,
            field_name=namespace,
            value=claim_value,
            claim_key=claim_key,
            note=note,
            citation_ref=citation_ref,
        )
        emitted_keys.append(claim_key)
    return emitted_keys


def _add_removals(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    existing: CatalogModel,
    entry: EditEntry,
    ct_id: int,
    source: Source,
    rel_namespaces: frozenset[str],
    rel_fields_by_model: dict[type[CatalogModel], set[str]],
    *,
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> _RemovalResult:
    """Emit ``exists=false`` member supersedes for each ``remove:`` member.

    Removing a relationship member is *not* a claim retraction (deactivation):
    it asserts a tombstone claim (``exists=false``) that supersedes this
    source's prior ``exists=true`` membership claim — exactly how the in-app
    editor drops a member (see ``build_m2m_claim_specs``). The resolver then
    drops the through-table row because no enabled source asserts the member
    present.

    Because the resolver unions ``exists=true`` across sources, the supersede
    only takes effect when attributed to the source holding the active
    membership claim. So this skips (with a warning, never erroring — re-runs
    stay safe) any member this source does not currently claim present, rather
    than writing an inert tombstone. The skip mirrors ``retract:``'s no-op
    behaviour for an already-absent scalar/FK claim.

    Returns a :class:`_RemovalResult`: every *intended* removal (for the clash
    guard, recorded regardless of the no-op skip) and whether any tombstone was
    actually emitted (a carrier, for the provenance check).
    """
    removed: dict[str, str] = {}
    carrier_written = False
    for namespace, members in entry.remove.items():
        if namespace not in rel_namespaces:
            raise PatchError(
                f"{entry.ref}: cannot remove from {namespace!r} — not a relationship "
                f"namespace on {model_class.__name__} (use 'retract:' for scalar/FK)"
            )
        rel_spec = _relationship_member_spec(model_class, namespace, entry)
        for member in members:
            member_pk = _resolve_member_pk(member, namespace, rel_spec, entry)
            claim_key, claim_value = build_relationship_claim(
                namespace, {rel_spec.value_key: member_pk}, exists=False
            )
            # Record the removal *intent* for the assert/remove conflict guard
            # before the no-op skip below. Asserting and removing the same member
            # is an authoring contradiction knowable from the patch text alone, so
            # it must be rejected regardless of whether this source currently
            # claims the member — otherwise the same nonsensical patch is caught
            # or silently applied depending on DB state. The skip only suppresses
            # the tombstone write, not the contradiction check.
            removed[claim_key] = f"{namespace} {member}"
            if not _source_claims_member_present(source, ct_id, existing.pk, claim_key):
                plan.warnings.append(
                    f"{entry.ref}: remove {namespace} member {member!r} is a no-op — "
                    f"{source.slug} has no active membership claim for it"
                )
                continue
            _emit_assert(
                plan,
                _Target(content_type_id=ct_id, object_id=existing.pk),
                field_name=namespace,
                value=claim_value,
                claim_key=claim_key,
                note=note,
                citation_ref=citation_ref,
            )
            rel_fields_by_model[model_class].add(namespace)
            carrier_written = True
    return _RemovalResult(removed_members=removed, carrier_written=carrier_written)


def _source_claims_member_present(
    source: Source,
    ct_id: int,
    object_id: int,
    claim_key: str,
) -> bool:
    """Does *source* hold an active ``exists=true`` claim for this member?

    True only when the source's winning claim for *claim_key* asserts presence —
    so an already-removed (``exists=false``) or never-claimed member reads as
    absent, and removing it would be an inert no-op.
    """
    value = (
        Claim.objects.filter(
            source=source,
            is_active=True,
            content_type_id=ct_id,
            object_id=object_id,
            claim_key=claim_key,
        )
        .values_list("value", flat=True)
        .first()
    )
    return isinstance(value, dict) and bool(value.get("exists", True))


def _add_create(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    entry: CreateEntry,
    handle: str,
    *,
    note: str = "",
) -> None:
    """Emit a ``PlannedEntityCreate`` plus its required identity/status claims.

    The author writes only the authored fields; the adapter supplies the
    public_id (from the entry key) and ``status='active'``, and feeds every
    claim-controlled kwarg into both the create kwargs *and* a matching
    assertion (the engine's create contract). Authored field assertions are
    emitted by the caller's field loop.

    Two identity shapes, distinguished model-drivenly by whether the public id
    *is* the form field:

    * **public id is the form field** (``slug`` for most entities) — the
      author never writes it; the adapter takes it from the entity reference
      and emits its claim here.
    * **public id is derived** (Location: ``location_path`` from parent +
      slug) — the author writes the form field (``slug``) and parent as normal
      claims; the adapter takes the derived public id from the reference, never
      claims it (it isn't claim-controlled), and verifies it composes from the
      authored claims via ``model_class.compose_public_id``.

    ``note`` rides the adapter-owned identity/status assertions so a
    create-only entry's note still reaches its ChangeSet. A ``cite:``
    deliberately does *not* ride the adapter-owned ones — the slug and the
    record-lifecycle status aren't sourced facts; the citation rides the
    authored field claims (the field loop) only.
    """
    pid_field = model_class.public_id_field
    form_field = model_class.public_id_form_field or pid_field
    claim_fields = get_claim_fields(model_class)
    derived_id = form_field != pid_field
    # The author's claim-based identity is the *form field*. For most entities
    # it *is* the public id (slug); for a derived public id it differs
    # (Location: slug → location_path). Either way it must be claim-controlled,
    # or the entity has no claimable identity and can't be created via a patch.
    if form_field not in claim_fields:
        raise PatchError(
            f"{entry.ref}: creating a {entry.entity_type} is not supported — its "
            f"public id ({pid_field}) is system-generated, not claim-based"
        )
    # Adapter-owned on a create: the public_id_field comes from the entity
    # reference and status is always 'active'. Authoring them would either
    # spawn an entity that doesn't match its reference or trip the engine's
    # create contract (status must be 'active'), so reject. The form field
    # itself (slug) stays author-writable on a derived create — only the
    # derived public id field is off-limits.
    adapter_owned = {pid_field, LIFECYCLE_STATUS_FIELD} & entry.fields.keys()
    if adapter_owned:
        raise PatchError(
            f"{entry.ref}: do not set {', '.join(sorted(adapter_owned))} on a create "
            f"— the public_id comes from the entity reference and status is "
            f"always 'active'"
        )
    # A derived public id is composed from the form field, so the author must
    # supply it (the reference can't stand in for it the way it does for slug).
    if derived_id and form_field not in entry.fields:
        raise PatchError(
            f"{entry.ref}: creating a {entry.entity_type} requires {form_field!r} "
            f"(its public id {pid_field!r} is derived from it)"
        )
    kwargs: dict[str, object] = {
        pid_field: entry.public_id,
        LIFECYCLE_STATUS_FIELD: "active",
    }

    for key, value in entry.fields.items():
        if key not in claim_fields:
            continue  # relationships are not model kwargs; emitted as claims
        django_field = model_class._meta.get_field(key)
        if isinstance(django_field, models.ForeignKey):
            target_model = django_field.related_model
            assert isinstance(target_model, type)  # resolved FK target
            if not isinstance(value, str):
                raise PatchError(f"{entry.ref}: FK {key!r} value must be a public_id")
            target_pk = _lookup_pk(target_model, value)
            if target_pk is None:
                raise PatchError(
                    f"{entry.ref}: FK {key!r} target {value!r} does not exist "
                    f"(creating an FK target in the same patch is unsupported)"
                )
            kwargs[django_field.attname] = target_pk
        else:
            kwargs[key] = value

    # Derived public id: the reference must equal what the authored claims
    # compose to, so a path that disagrees with its parent + slug fails loudly
    # instead of creating an internally inconsistent row.
    if derived_id:
        composed = model_class.compose_public_id(entry.fields)
        if composed != entry.public_id:
            raise PatchError(
                f"{entry.ref}: reference public id {entry.public_id!r} does not match "
                f"the {pid_field} composed from the claims ({composed!r})"
            )

    plan.entities.append(
        PlannedEntityCreate(model_class=model_class, kwargs=kwargs, handle=handle)
    )
    # The public-id claim is adapter-owned only when the public id *is* a claim
    # field (slug, absent from entry.fields) — emit it here. For a derived public
    # id the form field (slug) is a normal authored claim emitted by the
    # caller's field loop, and the derived field itself carries no claim.
    if pid_field in claim_fields:
        plan.assertions.append(
            PlannedClaimAssert(
                field_name=pid_field, value=entry.public_id, handle=handle, note=note
            )
        )
    plan.assertions.append(
        PlannedClaimAssert(
            field_name=LIFECYCLE_STATUS_FIELD,
            value="active",
            handle=handle,
            note=note,
        )
    )


def _add_delete(
    plan: IngestPlan,
    existing: CatalogModel,
    entry: DeleteEntry,
    *,
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> list[EntityKey]:
    """Emit ``status=deleted`` assertions to soft-delete *existing* and its cascade.

    A patch delete is a ``status=deleted`` claim, exactly like the in-app
    delete — no row removal. It reuses the app's :func:`plan_soft_delete` so it
    obeys the same record-lifecycle rules: it **refuses** when an active PROTECT
    referrer would be left dangling (reassign or delete the referrer first, in
    an earlier patch — the blocker check reads live DB state, so a same-patch
    reassignment isn't yet visible) and **cascades** ``status=deleted`` to owned
    lifecycle children.

    ``note``/``cite`` ride the emitted status claims (the entry's own carrier),
    so a delete entry needs no separate field assertion to anchor provenance.
    Idempotent: re-asserting ``status=deleted`` on an already-deleted entity
    diffs as unchanged, so a re-run is a clean no-op.

    Returns the ``(content_type_id, object_id)`` key of every entity this entry
    soft-deletes — root *and* cascade children — so the caller can register
    them all in the same-entity provenance guard (a cascaded child is otherwise
    invisible to it, and a separate entry on that child would collide unseen).
    """
    sd_plan = plan_soft_delete(existing)
    if sd_plan.is_blocked:
        blockers = "; ".join(
            f"{b.entity_type} {b.slug or b.name!r} (via {b.relation})"
            for b in sd_plan.blockers
        )
        raise PatchError(
            f"{entry.ref}: cannot delete — still referenced by "
            f"{len(sd_plan.blockers)} active entity(ies): {blockers}. Reassign or "
            f"delete the referrer first (in an earlier patch)."
        )
    affected: list[EntityKey] = []
    for target_entity in sd_plan.entities_to_delete:
        ct_id = ContentType.objects.get_for_model(type(target_entity)).pk
        _emit_assert(
            plan,
            _Target(content_type_id=ct_id, object_id=target_entity.pk),
            field_name=LIFECYCLE_STATUS_FIELD,
            value="deleted",
            note=note,
            citation_ref=citation_ref,
        )
        affected.append(EntityKey(ct_id, target_entity.pk))
    cascaded = [e for e in sd_plan.entities_to_delete if e.pk != existing.pk]
    if cascaded:
        members = ", ".join(f"{e.entity_type}.{e.public_id}" for e in cascaded)
        plan.warnings.append(
            f"{entry.ref}: delete cascades to {len(cascaded)} child entity(ies): {members}"
        )
    return affected


def _check_expect(
    model_class: type[CatalogModel],
    existing: CatalogModel,
    entry: EditEntry | DeleteEntry,
) -> None:
    """Drift guard: every ``expect:`` value must equal the resolved value.

    Piggybacks the entity already loaded for the claim target — no extra
    query for scalars, one related access for FKs. v1 covers scalar + FK;
    relationship-``expect`` is unsupported.
    """
    if not entry.expect:
        return
    claim_fields = get_claim_fields(model_class)
    for field_name, expected in entry.expect.items():
        if field_name not in claim_fields:
            raise PatchError(
                f"{entry.ref}: expect field {field_name!r} is not a scalar/FK field "
                f"(relationship-expect is unsupported in v1)"
            )
        django_field = model_class._meta.get_field(field_name)
        if isinstance(django_field, models.ForeignKey):
            related = getattr(existing, field_name)
            if related is None:
                actual: object = None
            else:
                pid_field = getattr(type(related), "public_id_field", "slug")
                actual = getattr(related, pid_field)
        else:
            actual = getattr(existing, field_name)
        if actual != expected:
            raise PatchError(
                f"{entry.ref}: expect {field_name}={expected!r} but the resolved "
                f"value is {actual!r}"
            )


def _add_retractions(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    existing: CatalogModel,
    entry: EditEntry,
    ct_id: int,
    source: Source,
    rel_namespaces: frozenset[str],
    *,
    note: str = "",
) -> bool:
    """Emit a ``PlannedClaimRetract`` per ``retract:`` field; return whether any fired.

    v1 covers scalar/FK fields only, where the claim key equals the field
    name (so the engine's identity match finds the active claim). Relationship
    retract is deferred. Each field must be a scalar/FK claim field on the
    (existing) entity.

    A retract only deactivates *this source's* active claim, so a field the
    source doesn't currently claim is an inert no-op: it's skipped with a warning
    (never erroring — re-runs stay safe), exactly as ``remove:`` skips a member
    the source doesn't hold. The build-time check matters for provenance — a
    no-op retraction writes no ChangeSet, so a ``note`` riding only no-op
    retractions has no carrier and must not be silently dropped. The return value
    reports whether at least one real retraction was emitted, so the caller's
    provenance-carrier check can reject such a note.
    """
    if not entry.retract:
        return False
    # Note: retract/assert conflicts (same field retracted and asserted on this
    # entity, in this or another entry) are caught plan-wide in build_plan.
    claim_fields = get_claim_fields(model_class)
    retracted_any = False
    for field_name in entry.retract:
        if field_name in rel_namespaces:
            raise PatchError(
                f"{entry.ref}: cannot retract relationship {field_name!r} "
                f"(relationship retract is unsupported in v1)"
            )
        if field_name not in claim_fields:
            raise PatchError(
                f"{entry.ref}: cannot retract {field_name!r} — not a scalar/FK claim "
                f"field on {model_class.__name__}"
            )
        if not _source_claims_field(source, ct_id, existing.pk, field_name):
            plan.warnings.append(
                f"{entry.ref}: retract {field_name!r} is a no-op — "
                f"{source.slug} has no active claim for it"
            )
            continue
        plan.retractions.append(
            PlannedClaimRetract(
                content_type_id=ct_id,
                object_id=existing.pk,
                claim_key=field_name,
                note=note,
            )
        )
        retracted_any = True
    return retracted_any


def _source_claims_field(
    source: Source,
    ct_id: int,
    object_id: int,
    claim_key: str,
) -> bool:
    """Does *source* hold an active scalar/FK claim for this field?

    The scalar/FK analogue of :func:`_source_claims_member_present` (no
    ``exists`` flag — a scalar/FK claim is present iff an active row exists).
    Used to detect a no-op ``retract:`` at build time.
    """
    return Claim.objects.filter(
        source=source,
        is_active=True,
        content_type_id=ct_id,
        object_id=object_id,
        claim_key=claim_key,
    ).exists()


def _make_resolve_hook(
    model_class: type[CatalogModel],
    field_names: list[str],
) -> Callable[..., None]:
    """Build a resolve hook that bulk-resolves the given relationship namespaces.

    Registered on the plan per content type and invoked by the apply engine with
    the affected ``subject_ids``. Resolves the whole set in a single pass per
    namespace (see ``resolve_relationships_bulk``) rather than re-resolving each
    entity individually — the per-object path re-loads FK lookup tables and
    re-runs every resolver once per object, which is O(N) full re-resolutions
    and dominates patch runtime on large patches.
    """

    def hook(*, subject_ids: set[int] | None = None) -> None:
        if not subject_ids:
            return
        resolve_relationships_bulk(model_class, field_names, set(subject_ids))

    return hook
