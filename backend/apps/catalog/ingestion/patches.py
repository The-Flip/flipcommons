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
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import NamedTuple, cast
from urllib.parse import urlparse

import yaml
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.api.soft_delete import plan_soft_delete
from apps.catalog.claims import (
    build_relationship_claim,
    get_relationship_namespaces,
    normalize_abbreviation_value,
    normalize_alias_identity,
)
from apps.catalog.ingestion.apply import (
    CitationRef,
    CiteHandle,
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
from apps.core.markdown import get_markdown_fields
from apps.core.models import LIFECYCLE_STATUS_FIELD
from apps.core.types import EntityKey, JsonBody
from apps.provenance.models import Claim, IdentityPart, Source, get_claim_fields
from apps.provenance.models.changeset import CHANGESET_NOTE_MAX_LENGTH
from apps.provenance.validation import get_relationship_schema

PATCH_ID_RE = re.compile(r"^\d{4}-[a-z0-9-]+$")

# Inline-citation marker scan. Deliberately BROADER than the wikilink registry's
# ``cite`` authoring pattern (which carries a ``(?!id:)`` negative lookahead):
# this captures *every* ``[[cite:...]]`` marker — including the ``[[cite:id:N]]``
# storage form — precisely so the strict-grammar classification below can reject a
# patch-authored raw-pk marker. Do NOT dedupe this against the registry pattern.
_CITE_MARKER_RE = re.compile(r"\[\[cite:([^\]]+)\]\]")
# Strict handle grammars — classification is purely lexical (no DB lookup). A real
# CitationInstance slug is constrained to 8 lowercase consonants, a strict subset
# of ``^[a-z]+$`` and provably disjoint from ``^[0-9]+$``, so a numeric new-handle
# can never masquerade as a slug or vice-versa.
_NUMERIC_HANDLE_RE = re.compile(r"^[0-9]+$")
_SLUG_HANDLE_RE = re.compile(r"^[a-z]+$")

# Keys in a claim entry's value mapping that are directives, not claim fields.
RESERVED_FIELD_KEYS = frozenset(
    {"create", "delete", "expect", "retract", "remove", "note", "cite", "cites"}
)

# The claim-controlled lifecycle field (``LifecycleStatusModel.status``), shared
# with the apply layer via ``apps.core.models``. Patches never write it directly
# — it's created as ``active`` and soft-deleted to ``deleted`` via the
# ``delete:`` directive, which routes through the soft-delete planner. A raw
# claim would skip that planner's safety checks.

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


# A ``remove:`` directive's shape: relationship namespace → member values to
# drop. (Both keys and members are bare ``str`` — a member is an FK public_id
# (tag, location) or a bare string (alias, abbreviation); the catalog keeps both
# uniformly untyped, so this alias names the structure without enforcing them.)
type RelationshipMembers = dict[str, list[str]]

# The composite key identifying one claim — a scalar/FK field name or a
# relationship member key from ``build_relationship_claim`` (e.g.
# ``"location:germany"``). A transparent alias of ``str``: it documents the
# concept where it recurs in this module without changing any interop with the
# ``str``-typed claim machinery (``apps.catalog.claims``, apply's ClaimIdentity).
type ClaimKey = str

# A catalog entity's public_id — the URL-identity value of its ``public_id_field``
# (``slug`` for most entities, ``location_path`` for Location), and what an FK or
# relationship member names its target by. A transparent alias of ``str`` like
# ``ClaimKey``: it distinguishes a public_id from the other ``str``s in this module
# (a handle/entry ``ref``, a relationship ``namespace``) at the points where the
# distinction is otherwise invisible — e.g. a ``dict[str, set[str]]`` adjacency map.
type PublicId = str


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
    # ``cite_archive`` is an optional durable-snapshot (Wayback) URL that rides
    # the same citation; only valid alongside a ``http(s)://`` ``cite``.
    # Empty when unset.
    note: str = ""
    cite: str = ""
    cite_archive: str = ""
    # Inline-citation specs for *new* footnotes referenced by numeric-handle
    # ``[[cite:1]]`` markers in this entry's markdown fields, keyed by the
    # patch-local handle (``"1"``). Each value is a parsed CitationRef minted at
    # apply time as a floating ``claim=None`` CitationInstance. Existing-slug
    # markers (``[[cite:<slug>]]``) need no entry here — they self-resolve. Empty
    # when unset; only ``CreateEntry``/``EditEntry`` ever populate it (a
    # ``DeleteEntry`` with ``cites:`` is rejected — no markdown claim to bind to).
    cites: dict[CiteHandle, CitationRef] = field(default_factory=dict)

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
    # of relationship namespace → members to drop by superseding each with an
    # ``exists=false`` tombstone (the claim stays active, resolving to "absent")
    # — exactly how the in-app editor drops a member. A member is an FK public_id
    # or a bare string (alias, abbreviation).
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
            f"list of member values (e.g. {{location: [germany]}})"
        )
    return cast(RelationshipMembers, raw)


def _parse_cites(raw_cites: object, ref: str) -> dict[CiteHandle, CitationRef]:
    """Parse a ``cites:`` map of ``{handle: cite-spec}`` into CitationRefs.

    Each value is a cite spec in the same grammar as the entry-level ``cite:``
    (a ``scheme:identifier``/URL string or a ``{url, archive}`` mapping), parsed
    through the shared :func:`_normalize_raw_cite` + :func:`_parse_cite_value`
    path so it dedups and errors identically. Handle keys are always strings —
    the strict YAML loader's ``_assert_json`` rejects a bare integer mapping key
    before this runs, so an unquoted ``1:`` is a parse error the adapter never
    sees. The handle *grammar* (numeric new-cite vs slug existing-cite) and
    marker↔map correspondence are enforced later, at process time, against the
    actual markdown markers.
    """
    if not isinstance(raw_cites, dict):
        raise PatchError(f"{ref}: 'cites' must be a mapping of handle to cite spec")
    parsed: dict[CiteHandle, CitationRef] = {}
    for handle, raw_spec in raw_cites.items():
        # _assert_json guarantees string keys; assert for the type-checker.
        assert isinstance(handle, str)
        spec_ref = f"{ref} cites[{handle!r}]"
        cite, archive = _normalize_raw_cite(raw_spec, spec_ref)
        if not cite:
            raise PatchError(f"{spec_ref}: cite spec must be non-empty")
        parsed[handle] = _parse_cite_value(cite, archive, spec_ref)
    return parsed


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
    cite, cite_archive = _normalize_raw_cite(raw_fields.get("cite", ""), ref)
    cites = _parse_cites(raw_fields.get("cites", {}), ref)
    # Authored claim fields: everything that isn't a reserved directive key.
    fields = {k: v for k, v in raw_fields.items() if k not in RESERVED_FIELD_KEYS}
    # ``cites`` is passed per-constructor below rather than spread here — its
    # ``dict[str, CitationRef]`` value would widen this all-``str`` mapping.
    common = {
        "entity_type": entity_type,
        "public_id": public_id,
        "note": note,
        "cite": cite,
        "cite_archive": cite_archive,
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
        return DeleteEntry(**common, cites=cites, expect=_parse_expect(raw_fields, ref))

    if create:
        for key in ("expect", "retract", "remove"):
            if key in raw_fields:
                raise PatchError(f"{ref}: {key!r} is meaningless on a create")
        return CreateEntry(**common, cites=cites, fields=fields)

    return EditEntry(
        **common,
        cites=cites,
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
    with empty field sets and ``from_delete=True``; an edit contributes one
    carrying its retract / assert / remove sets. ``_validate_plan_wide`` merges
    these across entries, enforcing per-entry-ChangeSet disjointness.

    ``deferred_member_ids`` are ``"namespace handle"`` keys for members pointing
    at a same-patch create — kept apart from ``asserted_members`` (concrete
    claim_keys) because their real claim_key isn't known until apply time, but
    still guarded for cross-entry duplication.
    """

    ref: str
    from_delete: bool
    retracted_fields: frozenset[str]
    asserted_fields: frozenset[str]
    asserted_members: frozenset[ClaimKey]
    deferred_member_ids: frozenset[str]
    # claim_key → "namespace public_id" label, for the assert/remove clash error.
    removed_members: dict[ClaimKey, str]


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

    removed_members: dict[ClaimKey, str]
    carrier_written: bool


class _CreatedKey(NamedTuple):
    """Identity of an entity created earlier in the same patch.

    Keyed by the *resolved concrete model class* (never the ``entity_type``
    label), so a later reference looks it up by the FK/relationship target's
    ``related_model`` — the same class ``_lookup_pk`` queries — with no
    ``"corporate-entity"`` vs ``corporate_entity`` or base-vs-concrete drift.

    Typed ``type[models.Model]`` (not ``type[CatalogModel]``) because lookups key
    by an FK target's ``related_model``, which Django only types as ``Model``; at
    runtime every catalog FK target *is* a ``CatalogModel``. The key is pure
    identity, so the wider annotation costs nothing.
    """

    model_class: type[models.Model]
    public_id: PublicId


class _MemberEmitResult(NamedTuple):
    """Outcome of ``_emit_relationship`` for one entry's namespace.

    ``clash_keys`` are the *concrete* claim_keys the assert/remove clash guard
    and ``asserted_members`` consume; a deferred (same-patch-created) member has
    no concrete claim_key at plan time, so its target ``handle`` rides
    ``deferred_handles`` instead — the cross-entry disjoint guard keys it as
    ``"namespace handle"`` so two entries asserting the same same-patch member
    can't silently collapse in ``_build_claims``. ``carrier_written`` is whether
    any assertion — concrete or deferred — was emitted, so a ``note:``/``cite:``
    on an entry whose members are *all* same-patch creates is not wrongly rejected
    by the provenance-carrier check.
    """

    clash_keys: list[ClaimKey]
    deferred_handles: list[str]
    carrier_written: bool


class _HierarchyEdge(NamedTuple):
    """A child→parent edge asserted into a self-referential hierarchy.

    Self-referential relationship namespaces (``theme_parent``,
    ``gameplay_feature_parent`` — structurally: a single FK identity whose
    target *is* the subject model) form a DAG. Each ``exists=true`` member is a
    child→parent edge, identified by public_id so same-patch creates (no PK yet)
    and existing rows share one namespace. Collected for the plan-wide acyclicity
    guard that the API enforces but the patch path otherwise bypasses.
    """

    namespace: str
    child: PublicId
    parent: PublicId
    ref: str  # the entry-ref/handle that asserted the edge, for the error message


class _RawCite(NamedTuple):
    """A ``cite:`` value split into its primary and durable-snapshot parts.

    ``cite`` is the raw ``scheme:identifier``/URL string; ``archive`` is the
    optional Wayback (or other) snapshot URL. Both ``""`` when unset.
    """

    cite: str
    archive: str


def _normalize_raw_cite(raw_cite: object, ref: str) -> _RawCite:
    """Split a raw ``cite:`` value into its ``cite`` and ``archive`` parts.

    Two authoring forms:

    * a bare ``scheme:identifier``/URL **string** → ``(cite, "")``;
    * a ``{url, archive}`` **mapping** → ``(url, archive)``, carrying a durable
      snapshot (Wayback) alongside the live page.

    Shape-only here; the URL/archive validity checks live in ``_parse_cite_url``.
    """
    if isinstance(raw_cite, str):
        return _RawCite(raw_cite, "")
    if isinstance(raw_cite, dict):
        extra = set(raw_cite) - {"url", "archive"}
        if extra:
            raise PatchError(
                f"{ref}: 'cite' mapping has unknown key(s) {sorted(extra)}; "
                f"allowed keys are 'url' and 'archive'"
            )
        url = raw_cite.get("url", "")
        archive = raw_cite.get("archive", "")
        if not isinstance(url, str) or not url:
            raise PatchError(f"{ref}: 'cite.url' must be a non-empty string")
        if not isinstance(archive, str):
            raise PatchError(f"{ref}: 'cite.archive' must be a string")
        return _RawCite(url, archive)
    raise PatchError(
        f"{ref}: 'cite' must be a 'scheme:identifier'/URL string or a "
        f"{{url, archive}} mapping"
    )


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
    if entry.cite_archive and not entry.cite.startswith(("http://", "https://")):
        raise PatchError(
            f"{entry.ref}: 'cite.archive' is only valid alongside a http(s):// "
            f"URL cite, not a scheme cite or an empty cite"
        )
    if not entry.cite:
        return note, None
    return note, _parse_cite_value(entry.cite, entry.cite_archive, entry.ref)


def _parse_cite_value(cite: str, archive: str, ref: str) -> CitationRef:
    """Parse one non-empty cite spec into a :class:`CitationRef`.

    Shared by the entry-level ``cite:`` (via :func:`_parse_provenance`) and the
    inline ``cites:`` map (:func:`_parse_cites`). Two forms:

    * a ``http(s)://`` URL — a standalone web source; an optional ``archive``
      durable-snapshot URL rides along;
    * ``scheme:identifier`` — the scheme must be a known extractor and the
      identifier must normalize (``ipdb:4443``).

    The empty-cite short-circuit and (for the entry path) the archive-without-URL
    guard stay with :func:`_parse_provenance`, which allows an absent cite; here
    ``cite`` is always non-empty.
    """
    if cite.startswith(("http://", "https://")):
        return _parse_cite_url(cite, archive, ref)
    if archive:
        raise PatchError(
            f"{ref}: 'cite.archive' is only valid alongside a http(s):// URL "
            f"cite, not a scheme cite"
        )
    scheme, sep, raw_id = cite.partition(":")
    if not sep or not scheme or not raw_id:
        raise PatchError(
            f"{ref}: cite {cite!r} must be 'scheme:identifier' (e.g. 'ipdb:4443')"
        )
    extractor = EXTRACTORS.get(scheme)
    if extractor is None:
        raise PatchError(
            f"{ref}: unknown cite scheme {scheme!r} "
            f"(known: {', '.join(sorted(EXTRACTORS))})"
        )
    normalized = extractor.normalize(raw_id)
    if normalized is None:
        raise PatchError(f"{ref}: invalid {scheme} identifier {raw_id!r}")
    if len(normalized) > CITATION_SOURCE_IDENTIFIER_MAX_LENGTH:
        raise PatchError(
            f"{ref}: cite identifier exceeds "
            f"{CITATION_SOURCE_IDENTIFIER_MAX_LENGTH} characters"
        )
    return CitationRef(scheme=scheme, identifier=normalized)


def _parse_cite_url(url: str, archive_url: str, ref: str) -> CitationRef:
    """Validate a ``http(s)://`` cite URL into a standalone-web CitationRef.

    Rejects a URL that matches a known scheme's record pattern (it has a
    canonical ``scheme:identifier`` form that dedups correctly), a malformed
    URL, and one too long for the link column.
    """
    for scheme, extractor in EXTRACTORS.items():
        identifier = extractor.extract(url)
        if identifier is not None:
            raise PatchError(
                f"{ref}: cite URL matches the {scheme} scheme — "
                f"cite it as {scheme}:{identifier} instead"
            )
    # The caller guarantees an http(s):// scheme, so a host is all that's left
    # to validate (``https://`` alone has none).
    if not urlparse(url).hostname:
        raise PatchError(f"{ref}: cite {url!r} is not a valid URL")
    if len(url) > CITATION_SOURCE_LINK_URL_MAX_LENGTH:
        raise PatchError(
            f"{ref}: cite URL exceeds {CITATION_SOURCE_LINK_URL_MAX_LENGTH} characters"
        )
    if archive_url:
        # Deliberately NOT scheme-checked: a Wayback URL embeds the original
        # page URL as a path segment, so an ipdb/opdb page would false-match.
        # It rides as a plain ``archive`` link, never domain-resolved to a root.
        if (
            not archive_url.startswith(("http://", "https://"))
            or not urlparse(archive_url).hostname
        ):
            raise PatchError(
                f"{ref}: cite archive {archive_url!r} is not a valid http(s):// URL"
            )
        if len(archive_url) > CITATION_SOURCE_LINK_URL_MAX_LENGTH:
            raise PatchError(
                f"{ref}: cite archive URL exceeds "
                f"{CITATION_SOURCE_LINK_URL_MAX_LENGTH} characters"
            )
    return CitationRef(url=url, archive_url=archive_url)


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
    # Registry of same-patch creates → handle, keyed by concrete model class +
    # public_id, so a *later* entry can reference an entity an *earlier* entry
    # creates (backward references). A miss falls through to the seed/earlier-
    # patch DB lookup; only neither-found errors. (Kept separate from
    # ``created_refs``: that dedups by the entry-ref label; this resolves by
    # concrete class + public_id — different keys, different jobs.)
    created: dict[_CreatedKey, str] = {}
    # child→parent edges asserted into self-referential hierarchies, for the
    # plan-wide acyclicity guard (the patch path's equivalent of the API's
    # plan_parent_claims self-link/cycle check).
    hierarchy_added: dict[type[CatalogModel], list[_HierarchyEdge]] = defaultdict(list)

    # Stamp each entry's emissions with its file-order index for per-entry
    # ChangeSet grouping (apply layer). An entry's assertions/retractions are all
    # appended during its own ``_process_entry`` call and land contiguously at the
    # end of the plan lists (single-pass, nothing else appends between entries),
    # so slice-stamping the tail after each call is exact — and avoids threading
    # ``entry_index`` through every ``_emit_*``/``_add_*`` helper.
    results: list[_EntryResult] = []
    for entry_index, entry in enumerate(doc.claims):
        assert_start = len(plan.assertions)
        retract_start = len(plan.retractions)
        results.append(
            _process_entry(
                plan,
                entry,
                source=source,
                rel_namespaces=rel_namespaces,
                rel_fields_by_model=rel_fields_by_model,
                created_refs=created_refs,
                created=created,
                hierarchy_added=hierarchy_added,
            )
        )
        for pca in plan.assertions[assert_start:]:
            pca.entry_index = entry_index
        for pcr in plan.retractions[retract_start:]:
            pcr.entry_index = entry_index
    plan.records_matched = sum(r.matched for r in results)
    _validate_plan_wide(results)
    _validate_hierarchy_acyclic(hierarchy_added)

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


def _classify_inline_cites(
    entry: CreateEntry | EditEntry,
    model_class: type[CatalogModel],
) -> dict[str, dict[CiteHandle, CitationRef]]:
    """Validate this entry's inline ``[[cite:...]]`` markers against its ``cites:`` map.

    Scans **every** markdown field of the entry (the gate — a marker with no
    backing never survives), classifies each handle by strict grammar, enforces
    marker↔map correspondence, and returns ``{field_name: {numeric_handle:
    CitationRef}}`` for each markdown field carrying ≥1 *new*-cite marker (the
    minting payload :func:`_emit_direct` attaches to its assertion). All checks
    are DB-free; existing-slug validity is enforced downstream by
    ``convert_authoring_to_storage`` (raises ``Cite not found`` on a bad slug).
    """
    markdown_fields = set(get_markdown_fields(model_class))
    md_values = {
        k: v
        for k, v in entry.fields.items()
        if k in markdown_fields and isinstance(v, str)
    }
    if entry.cites and not md_values:
        raise PatchError(
            f"{entry.ref}: 'cites:' requires a markdown-field claim to bind to — "
            f"none of this entry's fields is a citable description field"
        )

    per_field_numeric: dict[str, set[CiteHandle]] = {}
    all_numeric: set[CiteHandle] = set()
    for field_name, value in md_values.items():
        for handle in _CITE_MARKER_RE.findall(value):
            if _NUMERIC_HANDLE_RE.match(handle):
                per_field_numeric.setdefault(field_name, set()).add(handle)
                all_numeric.add(handle)
            elif _SLUG_HANDLE_RE.match(handle):
                continue  # existing-cite slug — resolved later by conversion
            else:
                raise PatchError(
                    f"{entry.ref}: malformed inline citation '[[cite:{handle}]]' in "
                    f"{field_name!r} — a handle must be all-digits (a new citation, "
                    f"needs a 'cites:' entry) or all-lowercase-letters (an existing "
                    f"cite slug); this rejects a raw-pk '[[cite:id:N]]'"
                )

    # Correspondence (DB-free, loud). A slug-keyed ``cites:`` entry is its own
    # misuse — check it before the generic "unreferenced" case so the message is
    # specific.
    cite_handles = set(entry.cites)
    slug_keyed = {h for h in cite_handles if not _NUMERIC_HANDLE_RE.match(h)}
    if slug_keyed:
        raise PatchError(
            f"{entry.ref}: 'cites:' key(s) {sorted(slug_keyed)} must be numeric "
            f"handles (e.g. '1') — an existing cite is named by its slug marker, "
            f"not declared in 'cites:'"
        )
    missing = all_numeric - cite_handles
    if missing:
        raise PatchError(
            f"{entry.ref}: inline citation handle(s) {sorted(missing)} have no "
            f"'cites:' entry to mint from"
        )
    unused = cite_handles - all_numeric
    if unused:
        raise PatchError(
            f"{entry.ref}: 'cites:' entr(y/ies) {sorted(unused)} are not referenced "
            f"by any '[[cite:N]]' marker"
        )

    return {
        field_name: {h: entry.cites[h] for h in handles}
        for field_name, handles in per_field_numeric.items()
    }


def _process_entry(
    plan: IngestPlan,
    entry: PatchEntry,
    *,
    source: Source,
    rel_namespaces: frozenset[str],
    rel_fields_by_model: dict[type[CatalogModel], set[str]],
    created_refs: set[str],
    created: dict[_CreatedKey, str],
    hierarchy_added: dict[type[CatalogModel], list[_HierarchyEdge]],
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

    # A delete carries no field assertions and no relationship work, so it
    # finishes here, registering every soft-deleted entity (root + cascade) with
    # the plan-wide guard as a *delete footprint*: decision 5 makes that footprint
    # exclusive, so any other entry touching one of these entities is rejected.
    if isinstance(entry, DeleteEntry):
        if entry.cites:
            raise PatchError(
                f"{entry.ref}: 'cites:' requires a markdown-field claim to bind to — "
                f"a delete entry takes no field assertions"
            )
        if existing is None:
            raise PatchError(f"{entry.ref}: no such {entry.entity_type} to delete")
        _check_expect(model_class, existing, entry)
        affected = _add_delete(
            plan, existing, entry, note=note, citation_ref=citation_ref
        )
        contributions = {
            tkey: _TargetContribution(
                ref=entry.ref,
                from_delete=True,
                retracted_fields=frozenset(),
                asserted_fields=frozenset(),
                asserted_members=frozenset(),
                deferred_member_ids=frozenset(),
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
        _add_create(plan, model_class, entry, entry.ref, created=created, note=note)
        # Register after _add_create, so a create's own *FK fields* (resolved
        # inside _add_create against earlier creates) can't point at itself. NB
        # this entry's *relationship* fields are emitted below, after this line,
        # so a same-entry self-referential member (theme_parent/
        # gameplay_feature_parent) IS resolvable here — self-link and cycle
        # safety for those is enforced separately by the plan-wide hierarchy
        # guard, not by registration timing.
        created[_CreatedKey(model_class, entry.public_id)] = entry.ref
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

    # Inline-citation markers in the entry's markdown fields: validate grammar +
    # marker↔``cites:`` correspondence (DB-free) and get the per-field new-cite
    # minting payloads. Runs once over the whole entry before emitting, so a
    # marker in any markdown field is gated even if that field is emitted later.
    inline_cites_by_field = _classify_inline_cites(entry, model_class)

    # Shared field loop (create + edit). Track which scalar/FK fields and which
    # relationship members were asserted on an *existing* entity — creates target
    # a handle, so object_id is None and they contribute nothing to the guards —
    # and whether any real claim carrier was written (for the provenance check).
    asserted_fields: set[str] = set()
    asserted_members: set[ClaimKey] = set()
    deferred_member_ids: set[str] = set()
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
            _emit_direct(
                plan,
                key,
                value,
                target,
                note=note,
                citation_ref=citation_ref,
                inline_cites=inline_cites_by_field.get(key, {}),
            )
            carrier_written = True
            if target.object_id is not None:
                asserted_fields.add(key)
        elif key in rel_namespaces:
            emit = _emit_relationship(
                plan,
                model_class,
                key,
                value,
                target,
                entry,
                created=created,
                hierarchy_added=hierarchy_added,
                note=note,
                citation_ref=citation_ref,
            )
            rel_fields_by_model[model_class].add(key)
            if emit.carrier_written:
                carrier_written = True
            if target.object_id is not None:
                # Concrete claim_keys feed the clash + disjoint guards; a deferred
                # (same-patch) member has no claim_key yet, so its target handle
                # rides a separate ``(namespace, handle)`` disjoint key.
                asserted_members.update(emit.clash_keys)
                deferred_member_ids.update(f"{key} {h}" for h in emit.deferred_handles)
        else:
            raise PatchError(f"{entry.ref}: unknown field {key!r}")

    # Relationship-member removals (exists=false supersede). Only an EditEntry
    # carries ``remove`` (create/delete reject it at parse time).
    removed_members: dict[ClaimKey, str] = {}
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
        from_delete=False,
        retracted_fields=frozenset(entry.retract),
        asserted_fields=frozenset(asserted_fields),
        asserted_members=frozenset(asserted_members),
        deferred_member_ids=frozenset(deferred_member_ids),
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


def _existing_parent_edges(
    model_class: type[CatalogModel],
) -> dict[PublicId, set[PublicId]]:
    """Current resolved child→parent public_id edges for a hierarchy model.

    ``parents`` is a runtime-generated self-M2M descriptor django-stubs can't
    see; the two ignores are confined to this boundary helper (same rationale as
    ``resolve._get_parents_through``). Only called for models that actually have
    the hierarchy ``parents`` M2M (those with a self-referential FK relationship).
    """
    edges: dict[PublicId, set[PublicId]] = {}
    queryset = model_class._default_manager.prefetch_related("parents")  # type: ignore[misc]
    for inst in queryset:
        parents: models.Manager[CatalogModel] = inst.parents  # type: ignore[attr-defined]
        edges[inst.public_id] = {p.public_id for p in parents.all()}
    return edges


def _reaches_via_parents(
    parent_map: dict[PublicId, set[PublicId]], start: PublicId, target: PublicId
) -> bool:
    """Walking parent edges up from *start*, is *target* reachable?

    ``start == target`` reaches trivially (used for the self-link case). Tolerant
    of pre-existing cycles in the graph via the ``seen`` guard.
    """
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(parent_map.get(node, ()))
    return False


def _validate_hierarchy_acyclic(
    hierarchy_added: dict[type[CatalogModel], list[_HierarchyEdge]],
) -> None:
    """Reject self-parent links and cycles in self-referential hierarchies.

    The patch path otherwise bypasses the API's ``plan_parent_claims`` guard, so
    a patch could assert ``gameplay_feature_parent: [self]`` or two mutually-
    referencing parents and silently corrupt the DAG (the resolver materializes
    whatever wins, with no self/cycle check).

    Conservative by design: the post-patch parent graph is the current resolved
    edges *plus* this patch's added edges, ignoring removals — so it never misses
    a cycle (a removal can only break one, and a removal that's a no-op for this
    source leaves the edge in place via another). A patch that both removes and
    re-adds around an edge may be over-rejected; split it across patches.
    """
    for model_class, edges in hierarchy_added.items():
        # Post-patch graph: current resolved edges + this patch's added edges.
        parent_map = _existing_parent_edges(model_class)
        for edge in edges:
            if edge.child == edge.parent:
                raise PatchError(
                    f"{edge.ref}: a {model_class.entity_type} cannot be its own "
                    f"parent ({edge.namespace})"
                )
            parent_map.setdefault(edge.child, set()).add(edge.parent)
        for edge in edges:
            # Adding child→parent closes a cycle iff parent already reaches child.
            if _reaches_via_parents(parent_map, edge.parent, edge.child):
                raise PatchError(
                    f"{edge.ref}: {edge.namespace} would create a cycle "
                    f"({edge.child} → {edge.parent} → … → {edge.child})"
                )


def _validate_plan_wide(results: list[_EntryResult]) -> None:
    """Run the cross-entry guards over all processed entries.

    With per-entry ChangeSets, several entries may target one entity — *provided*
    the claims they touch are disjoint. Each entry mints its own ChangeSet, and a
    claim_key shared by two entries would collapse in ``_build_claims`` /
    ``_process_retractions``, silently dropping one entry's grouping. Merges each
    entry's per-target contributions, enforcing on insert:

    1. **Disjoint claims (decision 2).** No scalar/FK field, concrete or deferred
       relationship member, or member tombstone may be asserted by two entries on
       one target; no field retracted by two entries.
    2. **Delete exclusivity (decision 5).** A delete soft-deletes its root +
       cascade as one ChangeSet, so no other entry may target any entity in that
       footprint.
    3. **No field both retracted and asserted** on one target (the assert wins,
       the retract is a silent no-op).
    4. **No member both asserted present and removed** on one target (both write
       the same claim_key — one would clobber the other).
    """
    target_ref: dict[EntityKey, str] = {}
    is_delete: dict[EntityKey, bool] = defaultdict(bool)
    entry_count: dict[EntityKey, int] = defaultdict(int)
    retracted_fields: dict[EntityKey, set[str]] = defaultdict(set)
    asserted_fields: dict[EntityKey, set[str]] = defaultdict(set)
    asserted_members: dict[EntityKey, set[ClaimKey]] = defaultdict(set)
    deferred_members: dict[EntityKey, set[str]] = defaultdict(set)
    removed_members: dict[EntityKey, dict[ClaimKey, str]] = defaultdict(dict)

    def _reject_dup[T](
        incoming: AbstractSet[T], seen: AbstractSet[T], ref: str, what: str
    ) -> None:
        dup = incoming & seen
        if dup:
            labels = ", ".join(sorted(str(d) for d in dup))
            raise PatchError(
                f"{ref}: {what} {labels} set by more than one entry on this record "
                f"— each entry is its own changeset, so combine them into one entry"
            )

    for result in results:
        for tkey, c in result.contributions.items():
            ref = c.ref
            entry_count[tkey] += 1
            target_ref[tkey] = ref
            if c.from_delete:
                is_delete[tkey] = True
            _reject_dup(c.asserted_fields, asserted_fields[tkey], ref, "field")
            _reject_dup(
                c.retracted_fields, retracted_fields[tkey], ref, "retracted field"
            )
            _reject_dup(c.asserted_members, asserted_members[tkey], ref, "member")
            _reject_dup(c.deferred_member_ids, deferred_members[tkey], ref, "member")
            _reject_dup(
                c.removed_members.keys(),
                removed_members[tkey].keys(),
                ref,
                "removed member",
            )
            retracted_fields[tkey] |= c.retracted_fields
            asserted_fields[tkey] |= c.asserted_fields
            asserted_members[tkey] |= c.asserted_members
            deferred_members[tkey] |= c.deferred_member_ids
            removed_members[tkey].update(c.removed_members)

    # Decision 5: a delete footprint is exclusive over root + cascade.
    for tkey, deleting in is_delete.items():
        if deleting and entry_count[tkey] > 1:
            raise PatchError(
                f"{target_ref[tkey]}: another entry targets an entity this patch "
                f"deletes (its root or a cascade child) — a delete must be the only "
                f"entry touching the entities it removes"
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
    claim_key: ClaimKey = "",
    note: str = "",
    citation_ref: CitationRef | None = None,
    inline_cites: dict[CiteHandle, CitationRef] | None = None,
) -> None:
    plan.assertions.append(
        PlannedClaimAssert(
            field_name=field_name,
            value=value,
            claim_key=claim_key,
            note=note,
            citation_ref=citation_ref,
            inline_cites=dict(inline_cites) if inline_cites else {},
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
    inline_cites: dict[CiteHandle, CitationRef] | None = None,
) -> None:
    """Emit a scalar or FK claim assertion (FK value is the target public_id).

    ``inline_cites`` carries any new (numeric-handle) inline citations to mint
    for a markdown field's value; empty for non-markdown fields and for markdown
    fields whose cites are all existing slugs.
    """
    _emit_assert(
        plan,
        target,
        field_name=field_name,
        value=value,
        note=note,
        citation_ref=citation_ref,
        inline_cites=inline_cites,
    )


class _FkMemberSpec(NamedTuple):
    """Member is a public_id resolving to an FK on another entity (tag, theme, location)."""

    value_key: str  # the value-dict key carrying the member FK (``spec.name``)
    target_model: type[models.Model]  # what a member public_id resolves to


class _StringMemberSpec(NamedTuple):
    """Member is a bare string (alias, abbreviation)."""

    value_key: str  # the value-dict key carrying the member string (``spec.name``)
    max_length: int  # the target CharField bound; over-length members are rejected
    # ``display_key`` is the either/or *within* string members: a sibling
    # value-key name (alias ⇒ case-fold via ``.lower()`` and carry display) or
    # ``None`` (abbreviation ⇒ stored verbatim). It is also the proxy for "this
    # identity case-folds" — a future string identity needing a different fold
    # must extend ``_member_identity``, not ride the ``.lower()`` default.
    display_key: str | None


# Closed discriminated union: an FK member never has a display key, a string
# member never has a target model — modelled so the illegal combinations are
# unrepresentable rather than guarded by nullable sentinels.
type _RelationshipMemberSpec = _FkMemberSpec | _StringMemberSpec


def _relationship_member_spec(
    model_class: type[CatalogModel],
    namespace: str,
    entry: PatchEntry,
) -> _RelationshipMemberSpec:
    """Classify *namespace* as a single-identity relationship on *model_class*.

    Shared by the assert (``_emit_relationship``) and remove (``_add_removals``)
    paths so both reject the same unsupported shapes with the same messages.
    Rejects an unknown namespace, one not valid on the subject model, a
    genuinely multi-key relationship (e.g. credit — still unsupported), and a
    single-identity relationship whose identity is neither an FK nor a string.

    Classification keys off declared schema properties (``fk_target``,
    ``scalar_type``, ``max_length``), never a model name or ``isinstance`` —
    so every FK-identity and string-identity relationship lights up uniformly.
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
    if len(identity_specs) != 1:
        raise PatchError(
            f"{entry.ref}: relationship {namespace!r} is not a single-key "
            f"relationship (multi-key relationships are unsupported)"
        )
    spec = identity_specs[0]
    if spec.fk_target is not None:
        return _FkMemberSpec(value_key=spec.name, target_model=spec.fk_target.model)
    if spec.scalar_type is str:
        if spec.max_length is None:
            raise PatchError(
                f"{entry.ref}: string relationship {namespace!r} has no declared "
                f"length bound (unsupported)"
            )
        return _StringMemberSpec(
            value_key=spec.name,
            max_length=spec.max_length,
            display_key=spec.display_key,
        )
    raise PatchError(
        f"{entry.ref}: relationship {namespace!r} has a non-FK, non-string "
        f"identity ({spec.scalar_type.__name__}) — unsupported"
    )


def _member_identity(
    member: object,
    namespace: str,
    rel_spec: _RelationshipMemberSpec,
    entry: PatchEntry,
) -> dict[str, IdentityPart]:
    """Build the value-dict identity for one relationship member, or raise.

    Returns the **same** dict for assert and remove — the removal caller passes
    it to ``build_relationship_claim(..., exists=False)``, which strips any
    non-identity key (e.g. ``alias_display``) to produce the canonical
    tombstone — so this stays the one authoritative identity builder.

    ``member`` is untyped parsed YAML, so each branch re-checks it is a ``str``
    at this boundary (a parse-edge guard, not a model-type branch).
    """
    match rel_spec:
        case _FkMemberSpec(value_key, target_model):
            if not isinstance(member, str):
                raise PatchError(
                    f"{entry.ref}: relationship {namespace!r} member {member!r} "
                    f"must be a public_id string"
                )
            member_pk = _lookup_pk(target_model, member)
            if member_pk is None:
                raise PatchError(
                    f"{entry.ref}: relationship {namespace!r} member {member!r} "
                    f"does not resolve to a {target_model.__name__}"
                )
            return {value_key: member_pk}
        case _StringMemberSpec(value_key, max_length, display_key):
            if not isinstance(member, str):
                raise PatchError(
                    f"{entry.ref}: relationship {namespace!r} member {member!r} "
                    f"must be a string"
                )
            stripped = member.strip()
            # Reject empty-after-strip loudly: the editor silently drops blanks,
            # so a "   " member here must error rather than become value="".
            if not stripped:
                raise PatchError(
                    f"{entry.ref}: relationship {namespace!r} has a blank member "
                    f"({member!r})"
                )
            if len(stripped) > max_length:
                raise PatchError(
                    f"{entry.ref}: relationship {namespace!r} member {member!r} "
                    f"exceeds the {max_length}-character limit"
                )
            # display_key present ⇒ alias (case-fold + carry display);
            # absent ⇒ abbreviation (verbatim). Shared fold keeps the algorithm
            # in one declarative place, byte-identical to the editor.
            if display_key is not None:
                ident = normalize_alias_identity(member)
                return {value_key: ident.value, display_key: ident.display}
            return {value_key: normalize_abbreviation_value(member)}


def _emit_relationship(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    namespace: str,
    value: object,
    target: _Target,
    entry: PatchEntry,
    *,
    created: dict[_CreatedKey, str],
    hierarchy_added: dict[type[CatalogModel], list[_HierarchyEdge]],
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> _MemberEmitResult:
    """Emit ``exists=true`` member assertions; return their clash keys + carrier flag.

    A member that resolves against the DB is emitted concretely (its ``claim_key``
    is recorded for the plan-wide assert/remove conflict guard). An FK member that
    instead names a *same-patch* create is emitted **deferred**
    (``relationship_namespace`` + ``identity_refs``), resolved post-creation in
    ``_patch_handles`` — it has no concrete claim_key yet, so it stays out of the
    clash list (the remove path can't reference a same-patch create at all, so
    there is nothing to clash with). Either way a carrier is written.
    """
    rel_spec = _relationship_member_spec(model_class, namespace, entry)
    if not isinstance(value, list):
        raise PatchError(
            f"{entry.ref}: relationship {namespace!r} value must be a list of members"
        )
    clash_keys: list[ClaimKey] = []
    deferred_handles: list[str] = []
    seen_keys: set[ClaimKey] = set()
    # Deferred members lack a concrete claim_key, so dedup them on the target
    # handle (the namespace is fixed for this call) to keep the same "duplicate
    # member" strictness as the concrete path's seen_keys.
    seen_deferred: set[str] = set()
    carrier_written = False
    # A relationship whose FK identity targets its own subject model is a
    # self-referential hierarchy (theme_parent/gameplay_feature_parent); record
    # each asserted edge for the plan-wide acyclicity guard, whether the parent
    # is an existing row or a same-patch create.
    is_self_hierarchy = (
        isinstance(rel_spec, _FkMemberSpec) and rel_spec.target_model is model_class
    )
    for member in value:
        if is_self_hierarchy and isinstance(member, str):
            hierarchy_added[model_class].append(
                _HierarchyEdge(
                    namespace=namespace,
                    child=entry.public_id,
                    parent=member,
                    ref=entry.ref,
                )
            )
        if isinstance(rel_spec, _FkMemberSpec) and isinstance(member, str):
            handle = created.get(_CreatedKey(rel_spec.target_model, member))
            if handle is not None:
                if handle in seen_deferred:
                    raise PatchError(
                        f"{entry.ref}: duplicate member {member!r} in {namespace!r}"
                    )
                seen_deferred.add(handle)
                deferred_handles.append(handle)
                plan.assertions.append(
                    PlannedClaimAssert(
                        field_name=namespace,
                        relationship_namespace=namespace,
                        identity_refs={rel_spec.value_key: handle},
                        note=note,
                        citation_ref=citation_ref,
                        content_type_id=target.content_type_id,
                        object_id=target.object_id,
                        handle=target.handle,
                    )
                )
                carrier_written = True
                continue
        identity = _member_identity(member, namespace, rel_spec, entry)
        claim_key, claim_value = build_relationship_claim(namespace, identity)
        # Reject a post-fold duplicate within one entry (e.g. [Stern, stern] →
        # same alias identity): emitting the same claim_key twice into one plan
        # is an authoring error, clearer rejected than silently collapsed. Keyed
        # on claim_key (the schema identity), not the full dict — alias_display
        # differs between "Stern"/"stern" but the identity collides.
        if claim_key in seen_keys:
            raise PatchError(
                f"{entry.ref}: duplicate member {member!r} in {namespace!r}"
            )
        seen_keys.add(claim_key)
        _emit_assert(
            plan,
            target,
            field_name=namespace,
            value=claim_value,
            claim_key=claim_key,
            note=note,
            citation_ref=citation_ref,
        )
        clash_keys.append(claim_key)
        carrier_written = True
    return _MemberEmitResult(
        clash_keys=clash_keys,
        deferred_handles=deferred_handles,
        carrier_written=carrier_written,
    )


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
    removed: dict[ClaimKey, str] = {}
    carrier_written = False
    for namespace, members in entry.remove.items():
        if namespace not in rel_namespaces:
            raise PatchError(
                f"{entry.ref}: cannot remove from {namespace!r} — not a relationship "
                f"namespace on {model_class.__name__} (use 'retract:' for scalar/FK)"
            )
        rel_spec = _relationship_member_spec(model_class, namespace, entry)
        seen_keys: set[ClaimKey] = set()
        for member in members:
            identity = _member_identity(member, namespace, rel_spec, entry)
            claim_key, claim_value = build_relationship_claim(
                namespace, identity, exists=False
            )
            # Reject an intra-list duplicate member (same fold → same claim_key),
            # mirroring the assert path's strictness.
            if claim_key in seen_keys:
                raise PatchError(
                    f"{entry.ref}: duplicate member {member!r} in {namespace!r}"
                )
            seen_keys.add(claim_key)
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
    claim_key: ClaimKey,
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
    created: dict[_CreatedKey, str],
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
    # FK columns whose target is created earlier in this same patch: deferred to
    # the target handle's PK by the apply layer (resolved after the bulk-create).
    # The field loop still emits the concrete provenance claim, which
    # _validate_entity_claim_consistency pairs with this handle_ref.
    handle_refs: dict[str, str] = {}

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
            if target_pk is not None:
                kwargs[django_field.attname] = target_pk
            else:
                ref_handle = created.get(_CreatedKey(target_model, value))
                if ref_handle is None:
                    raise PatchError(
                        f"{entry.ref}: FK {key!r} target {value!r} is not in the "
                        f"seed, an earlier patch, or this patch"
                    )
                handle_refs[django_field.attname] = ref_handle
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
        PlannedEntityCreate(
            model_class=model_class,
            kwargs=kwargs,
            handle=handle,
            handle_refs=handle_refs,
        )
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
    claim_key: ClaimKey,
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
