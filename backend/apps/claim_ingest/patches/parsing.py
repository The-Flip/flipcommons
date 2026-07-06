"""Parse layer: patch text → :class:`PatchDoc` (pure, no DB).

Strict YAML load (duplicate keys rejected), the entry grammar
(``create``/``edit``/``delete`` directives) and ``cite:`` value/URL parsing.
Produces the ``PatchDoc`` and entry dataclasses the rest of the package
consumes; depends only on :mod:`._types`. Validation that needs DB state happens
later in :mod:`.planning`, not here. Entry point: :func:`load_patch`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import NamedTuple, cast
from urllib.parse import urlparse

import yaml
from django.core.exceptions import ValidationError

from apps.citation.citation_types import (
    is_known_scheme,
    known_scheme_keys,
    normalize_scheme_identifier,
    recognize_scheme,
    scheme_source_type,
)
from apps.citation.locators import normalized_locator
from apps.citation.models import (
    CITATION_INSTANCE_LOCATOR_MAX_LENGTH,
    CITATION_INSTANCE_QUOTE_MAX_LENGTH,
    CITATION_SOURCE_IDENTIFIER_MAX_LENGTH,
    CITATION_SOURCE_LINK_URL_MAX_LENGTH,
)
from apps.citation.source_node import SourceLinkNode, SourceNode
from apps.claim_ingest.patches._types import PatchError
from apps.claim_ingest.plan import (
    CitationRef,
    CiteHandle,
    CiteSpec,
    SchemeCitationRef,
    WebCitationRef,
)
from apps.core.types import JsonBody
from apps.core.validators import validate_no_mojibake
from apps.provenance.models.changeset import CHANGESET_NOTE_MAX_LENGTH

PATCH_ID_RE = re.compile(r"^\d{4}-[a-z0-9-]+$")

# Inline-citation marker scan. Deliberately BROADER than the wikilink registry's
# ``cite`` authoring pattern (which carries a ``(?!id:)`` negative lookahead):
# this captures *every* ``[[cite:...]]`` marker — including the ``[[cite:id:N]]``
# storage form — precisely so the strict-grammar classification in :mod:`.planning`
# can reject a patch-authored raw-pk marker. Do NOT dedupe it against the registry.
_CITE_MARKER_RE = re.compile(r"\[\[cite:([^\]]+)\]\]")
# Strict handle grammars — classification is purely lexical (no DB lookup). A real
# CitationInstance slug is constrained to 8 lowercase consonants, a strict subset
# of ``^[a-z]+$`` and provably disjoint from ``^[0-9]+$``, so a numeric new-handle
# can never masquerade as a slug or vice-versa.
_NUMERIC_HANDLE_RE = re.compile(r"^[0-9]+$")
_SLUG_HANDLE_RE = re.compile(r"^[a-z]+$")

# Keys in a claim entry's value mapping that are directives, not claim fields.
#
# Grammar mirror: pindata's `schema/patch.schema.json` is a hand-maintained JSON
# Schema of this patch *wire* grammar. It's a structural pre-check for authors,
# living in the repo where patches are written, run by pindata's `make validate`.
# It's deliberately partial (this parser and planning stay authoritative) and
# can't see this file, so when you change the wire grammar here, update
# `patch.schema.json` in pindata to match.
RESERVED_FIELD_KEYS = frozenset(
    {
        "create",
        "delete",
        # ``expect`` is obsolete, now accepted-but-ignored: it stays
        # reserved so older patches that carry it still parse
        "expect",
        "retract",
        "remove",
        "note",
        "cite",
        "cites",
        "changesets",
    }
)

# Header-only keys a grouped `changesets:` item may not carry: lifecycle
# (create/delete) lives on the group header, and a nested changesets is
# meaningless.
_CHANGESET_ITEM_FORBIDDEN_KEYS = frozenset({"create", "delete", "changesets"})

# Allowed keys in a `sources:` node / its links, derived from the source-node
# TypedDicts (the single source of truth). `children` is excluded — v1 sources
# are flat.
ALLOWED_SOURCE_KEYS = frozenset(SourceNode.__annotations__) - {"children"}
ALLOWED_LINK_KEYS = frozenset(SourceLinkNode.__annotations__)


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


# One parsed relationship member: a bare public_id/string (tag, location, alias,
# abbreviation) or a one-key ``{person: role}`` mapping for credit, the lone
# multi-key relationship. YAML can hand us any dict; the single-key invariant on
# the mapping is enforced in the emitter (``_unpack_credit_member``), so the
# parse layer keeps members uniformly loose rather than encoding a shape it
# can't fully express in the type system.
type RelationshipMemberValue = str | dict[str, str]
# A ``remove:`` directive's shape: relationship namespace → member values to
# drop. (Keys are bare ``str``; members are :data:`RelationshipMemberValue` — the
# catalog keeps both uniformly untyped, so this alias names the structure without
# enforcing them.)
type RelationshipMembers = dict[str, list[RelationshipMemberValue]]


@dataclass(frozen=True, kw_only=True)
class _PatchEntry:
    """Common to every claim entry: the entity reference and provenance.

    Subclassed by the three entry kinds — :class:`CreateEntry`,
    :class:`EditEntry`, :class:`DeleteEntry`. The kind is decided while
    parsing, from the ``create:``/``delete:`` directives, and each subclass
    carries *only* the fields legal for that kind. So an illegal combination
    (``retract`` on a create, ``remove`` on a delete, a field assertion on a
    delete, …) is a parse-time error rather than a runtime flag check, and
    ``build_plan`` dispatches on the entry's *type* instead of re-testing
    boolean combinations.
    """

    entity_type: str
    public_id: str
    # Per-entry provenance, common to all kinds. ``note`` becomes the entity's
    # ChangeSet note; ``cite`` is a raw ``scheme:identifier`` string or a
    # ``http(s)://`` URL, parsed + validated into a CiteSpec in build_plan.
    # ``cite_archive`` is an optional durable-snapshot (Wayback) URL that rides
    # the same citation; only valid alongside a ``http(s)://`` ``cite``.
    # ``cite_locator``/``cite_quote`` are the minted CitationInstance's fields:
    # where in the source, and the verbatim excerpt. Empty when unset.
    note: str = ""
    cite: str = ""
    cite_archive: str = ""
    cite_locator: str = ""
    cite_quote: str = ""
    # Inline-citation specs for *new* footnotes referenced by numeric-handle
    # ``[[cite:1]]`` markers in this entry's markdown fields, keyed by the
    # patch-local handle (``"1"``). Each value is a parsed CiteSpec minted at
    # apply time as a floating CitationInstance (reached only by its marker),
    # carrying the same optional locator/quote as the entry-level ``cite:``.
    # Existing-slug markers (``[[cite:<slug>]]``) need no entry here — they
    # self-resolve. Empty when unset; only ``CreateEntry``/``EditEntry`` ever
    # populate it (a ``DeleteEntry`` with ``cites:`` is rejected — no markdown
    # claim to bind to).
    cites: dict[CiteHandle, CiteSpec] = field(default_factory=dict)

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

    Carries provenance only — no field assertions, ``retract`` or ``remove``
    (reassign any references in an earlier patch, before the delete).
    """


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
    sources: list[SourceNode] = field(default_factory=list)


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


def _parse_source_node(entry: object, where: str) -> SourceNode:
    """Validate one `sources:` node's shape and return it as a SourceNode.

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
    raw_domains = entry.get("domains", [])
    if not isinstance(raw_domains, list) or not all(
        isinstance(d, str) and d for d in raw_domains
    ):
        raise PatchError(f"{where}: 'domains' must be a list of non-empty strings")
    raw_links = entry.get("links", [])
    if not isinstance(raw_links, list):
        raise PatchError(f"{where}: 'links' must be a list")
    for j, link in enumerate(raw_links):
        _parse_link_shape(link, f"{where}.links[{j}]")
    # Shape-validated above; narrow the JSON dict to the source-node TypedDict.
    return cast(SourceNode, entry)


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


def _parse_retract(raw_fields: JsonBody, ref: str) -> list[str]:
    raw = raw_fields.get("retract", [])
    if not isinstance(raw, list) or not all(isinstance(f, str) for f in raw):
        raise PatchError(f"{ref}: 'retract' must be a list of field names")
    return cast(list[str], raw)


def _parse_remove(raw_fields: JsonBody, ref: str) -> RelationshipMembers:
    raw = raw_fields.get("remove", {})
    # A member is a bare string (single-key relationship) or a one-key mapping
    # (the multi-key credit relationship — ``{person: role}``). Shape is checked
    # shallowly here (``str`` or ``dict``); the emitter's ``_unpack_credit_member``
    # enforces the one-key string→string invariant on the mapping.
    if not isinstance(raw, dict) or not all(
        isinstance(namespace, str)
        and isinstance(members, list)
        and all(isinstance(m, str | dict) for m in members)
        for namespace, members in raw.items()
    ):
        raise PatchError(
            f"{ref}: 'remove' must be a mapping of relationship namespace to a "
            f"list of member values (e.g. {{location: [germany]}})"
        )
    return cast(RelationshipMembers, raw)


def _parse_cites(raw_cites: object, ref: str) -> dict[CiteHandle, CiteSpec]:
    """Parse a ``cites:`` map of ``{handle: cite-spec}`` into CiteSpecs.

    Each value is a cite spec in the same grammar as the entry-level ``cite:``
    (a ``scheme:identifier``/URL string or a ``{ref, archive, locator, quote}``
    mapping), parsed through the shared :func:`_normalize_raw_cite` +
    :func:`_parse_cite_value` + :func:`_validated_cite_instance_fields` path so
    it dedups and errors identically — ``locator``/``quote`` land on the minted
    inline instance exactly as they do on an entry-level cite. Handle keys are
    always strings — the strict YAML loader's ``_assert_json`` rejects a bare
    integer mapping key before this runs, so an unquoted ``1:`` is a parse
    error the adapter never sees. The handle *grammar* (numeric new-cite vs
    slug existing-cite) and marker↔map correspondence are enforced later, at
    process time, against the actual markdown markers.
    """
    if not isinstance(raw_cites, dict):
        raise PatchError(f"{ref}: 'cites' must be a mapping of handle to cite spec")
    parsed: dict[CiteHandle, CiteSpec] = {}
    for handle, raw_spec in raw_cites.items():
        # _assert_json guarantees string keys; assert for the type-checker.
        assert isinstance(handle, str)
        spec_ref = f"{ref} cites[{handle!r}]"
        cite, archive, locator, quote = _normalize_raw_cite(raw_spec, spec_ref)
        if not cite:
            raise PatchError(f"{spec_ref}: cite spec must be non-empty")
        cite_ref = _parse_cite_value(cite, archive, spec_ref)
        locator, quote = _validated_cite_instance_fields(
            cite_ref, locator, quote, spec_ref
        )
        parsed[handle] = CiteSpec(ref=cite_ref, locator=locator, quote=quote)
    return parsed


def _split_entry_ref(raw_entry: object, index: int) -> tuple[str, JsonBody]:
    """Unwrap a single-key ``{ref: body}`` claim entry into its ref and body.

    Job (a) of parsing a claim: validate the structural shape (single-key
    mapping, ``type.public_id`` ref, mapping body) and narrow ``object`` to the
    typed ``(ref, body)`` pair :func:`_parse_entry_body` consumes. ``index``
    locates the pre-ref structural errors — the only locator available before a
    ref exists.
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
    return ref, cast(JsonBody, raw_fields)


def _parse_entry_body(ref: str, raw_fields: JsonBody) -> PatchEntry:
    """Parse + structurally validate a claim entry's body into a typed kind.

    Job (b) of parsing a claim: with the ref and body already unwrapped and
    typed, decide the entry kind from ``create:``/``delete:`` and validate that
    the entry carries only the directives legal for that kind — so an illegal
    combination is rejected here, at parse time, rather than by flag checks in
    ``build_plan``. Field *values* and DB resolution stay in ``build_plan``.
    """
    entity_type, public_id = ref.split(".", 1)

    create = _require_bool(raw_fields, "create", ref)
    delete = _require_bool(raw_fields, "delete", ref)
    note = _require_str(raw_fields, "note", ref)
    cite, cite_archive, cite_locator, cite_quote = _normalize_raw_cite(
        raw_fields.get("cite", ""), ref
    )
    cites = _parse_cites(raw_fields.get("cites", {}), ref)
    # Authored claim fields: everything that isn't a reserved directive key.
    fields = {k: v for k, v in raw_fields.items() if k not in RESERVED_FIELD_KEYS}
    # ``cites`` is passed per-constructor below rather than spread here — its
    # ``dict[str, CiteSpec]`` value would widen this all-``str`` mapping.
    common = {
        "entity_type": entity_type,
        "public_id": public_id,
        "note": note,
        "cite": cite,
        "cite_archive": cite_archive,
        "cite_locator": cite_locator,
        "cite_quote": cite_quote,
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
        return DeleteEntry(**common, cites=cites)

    if create:
        for key in ("retract", "remove"):
            if key in raw_fields:
                raise PatchError(f"{ref}: {key!r} is meaningless on a create")
        return CreateEntry(**common, cites=cites, fields=fields)

    return EditEntry(
        **common,
        cites=cites,
        retract=_parse_retract(raw_fields, ref),
        remove=_parse_remove(raw_fields, ref),
        fields=fields,
    )


def _parse_claim(raw_entry: object, index: int) -> list[PatchEntry]:
    """Parse one ``claims:`` entry into one or more typed entries.

    Flat form (no ``changesets:`` key) → a single-element list, identical to
    parsing the body directly. Grouped form (a ``changesets:`` list) desugars
    into the existing flat :class:`PatchEntry` union at parse time, so nothing
    downstream changes:

    * the header's body **minus** ``changesets:`` is parsed as a normal entry —
      the *primary*, present only if the header asserts something (a ``create``,
      fields, a ``retract``/``remove``);
    * each ``changesets:`` item becomes an additional :class:`EditEntry` on the
      same record, inheriting the header's ref.

    Entries come back in file order — primary (if any) first, then the items —
    which is byte-identical to the flat multi-entry equivalent.
    """
    ref, body = _split_entry_ref(raw_entry, index)
    if "changesets" not in body:
        return [_parse_entry_body(ref, body)]

    header = {k: v for k, v in body.items() if k != "changesets"}
    # Carrier keys are everything that can anchor a ChangeSet: field assertions,
    # create/delete, retract/remove. The accepted-but-ignored ``expect`` and the
    # provenance keys can't.
    carrier_keys = set(header) - {"expect", "note", "cite", "cites"}
    provenance_keys = {"note", "cite", "cites"} & set(header)
    # A header with provenance but no carrier has nothing to attach it to: there
    # is no group-level note/cite, those ride the individual changesets. Reject
    # here with a clear message rather than letting the synthesized carrier-less
    # primary die in planning's opaque carrier check.
    if provenance_keys and not carrier_keys:
        raise PatchError(
            f"{ref}: a group header with no field assertions takes no "
            f"{', '.join(sorted(provenance_keys))} — put provenance on the "
            f"individual changesets"
        )

    entries: list[PatchEntry] = []
    if carrier_keys:  # header asserts something → it is the primary entry
        primary = _parse_entry_body(ref, header)
        if isinstance(primary, DeleteEntry):
            raise PatchError(f"{ref}: 'delete' can't be combined with 'changesets'")
        entries.append(primary)

    raw_changesets = body["changesets"]
    if not isinstance(raw_changesets, list) or not raw_changesets:
        raise PatchError(f"{ref}: 'changesets' must be a non-empty list of mappings")
    for item in raw_changesets:
        if not isinstance(item, dict):
            raise PatchError(f"{ref}: each 'changesets' item must be a mapping")
        forbidden = _CHANGESET_ITEM_FORBIDDEN_KEYS & set(item)
        if forbidden:
            raise PatchError(
                f"{ref}: a 'changesets' item may not carry "
                f"{', '.join(sorted(forbidden))} — these are header-only"
            )
        entries.append(_parse_entry_body(ref, item))
    return entries


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

    claims = [e for i, rc in enumerate(raw_claims) for e in _parse_claim(rc, i)]

    return PatchDoc(
        attribution=attribution,
        description=description,
        claims=claims,
        fingerprint=fp,
        sources=sources,
    )


class _RawCite(NamedTuple):
    """A ``cite:`` value split into its constituent parts.

    ``cite`` is the raw ``scheme:identifier``/URL string; ``archive`` is the
    optional Wayback (or other) snapshot URL; ``locator`` and ``quote`` are the
    minted instance's fields. All ``""`` when unset.
    """

    cite: str
    archive: str
    locator: str
    quote: str


_CITE_MAPPING_KEYS = frozenset({"ref", "archive", "locator", "quote"})


def _normalize_raw_cite(raw_cite: object, ref: str) -> _RawCite:
    """Split a raw ``cite:`` value into its constituent parts.

    Two authoring forms:

    * a bare ``scheme:identifier``/URL **string** → ``(cite, "", "", "")``;
    * a ``{ref, archive, locator, quote}`` **mapping** — ``ref`` takes the
      exact scalar grammar; ``archive`` carries a durable snapshot (Wayback)
      alongside a live URL; ``locator``/``quote`` land on the minted
      ``CitationInstance``.

    Shape-only here; the URL/archive validity checks live in ``_parse_cite_url``
    and the locator/quote checks in ``_validated_cite_instance_fields``, shared
    by the entry-level (``_parse_provenance``) and inline (``_parse_cites``)
    paths.
    """
    if isinstance(raw_cite, str):
        return _RawCite(raw_cite, "", "", "")
    if isinstance(raw_cite, dict):
        extra = set(raw_cite) - _CITE_MAPPING_KEYS
        if extra:
            raise PatchError(
                f"{ref}: 'cite' mapping has unknown key(s) {sorted(extra)}; "
                f"allowed keys are {', '.join(sorted(_CITE_MAPPING_KEYS))}"
            )
        cite = raw_cite.get("ref", "")
        if not isinstance(cite, str) or not cite:
            raise PatchError(f"{ref}: 'cite.ref' must be a non-empty string")
        parts = {}
        for key in ("archive", "locator", "quote"):
            value = raw_cite.get(key, "")
            if not isinstance(value, str):
                raise PatchError(f"{ref}: 'cite.{key}' must be a string")
            parts[key] = value
        return _RawCite(cite, parts["archive"], parts["locator"], parts["quote"])
    raise PatchError(
        f"{ref}: 'cite' must be a 'scheme:identifier'/URL string or a "
        f"{{ref, archive, locator, quote}} mapping"
    )


def _parse_provenance(entry: PatchEntry) -> tuple[str, CiteSpec | None]:
    """Validate an entry's ``note``/``cite`` and parse ``cite`` into a CiteSpec.

    Length-checks each value against the DB column it lands in so an overlong
    value fails as a clear :class:`PatchError` here rather than deep in
    persistence — and mojibake-checks ``locator``/``quote``, which the bulk
    mint path (``mint_many`` → ``bulk_create``) would otherwise never validate.
    ``cite``'s ref is one of two forms:

    * ``scheme:identifier`` — the scheme must be a registered scheme and the
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
        if entry.cite_locator or entry.cite_quote:
            raise PatchError(
                f"{entry.ref}: 'cite.locator'/'cite.quote' need a 'cite.ref' "
                f"to attach to"
            )
        return note, None
    cite_ref = _parse_cite_value(entry.cite, entry.cite_archive, entry.ref)
    locator, quote = _validated_cite_instance_fields(
        cite_ref, entry.cite_locator, entry.cite_quote, entry.ref
    )
    return note, CiteSpec(ref=cite_ref, locator=locator, quote=quote)


def _validated_cite_instance_fields(
    cite_ref: CitationRef, locator: str, quote: str, ref: str
) -> tuple[str, str]:
    """Validate + normalize a cite's minted-instance fields → ``(locator, quote)``.

    Shared by the entry-level ``cite:`` (:func:`_parse_provenance`) and inline
    ``cites:`` (:func:`_parse_cites`) paths so both validate identically:
    length-caps each value against the DB column it lands in and mojibake-checks
    both — necessary because the bulk mint path (``mint_many`` → ``bulk_create``)
    never runs model validation — then canonicalizes the locator against the
    resolved source's citation type (see :func:`_normalized_cite_locator`).
    """
    if len(locator) > CITATION_INSTANCE_LOCATOR_MAX_LENGTH:
        raise PatchError(
            f"{ref}: cite locator exceeds "
            f"{CITATION_INSTANCE_LOCATOR_MAX_LENGTH} characters"
        )
    if len(quote) > CITATION_INSTANCE_QUOTE_MAX_LENGTH:
        raise PatchError(
            f"{ref}: cite quote exceeds {CITATION_INSTANCE_QUOTE_MAX_LENGTH} characters"
        )
    for label, value in (("locator", locator), ("quote", quote)):
        try:
            validate_no_mojibake(value)
        except ValidationError as exc:
            raise PatchError(f"{ref}: cite {label}: {'; '.join(exc.messages)}") from exc
    return _normalized_cite_locator(cite_ref, locator, ref), quote


def _normalized_cite_locator(cite_ref: CitationRef, locator: str, ref: str) -> str:
    """Validate + canonicalize a cite's locator against its citation type.

    A scheme cite's citation type is known at parse time (the scheme declares
    what its children mint as), so a malformed video timestamp fails the patch
    here — with the entry ref in the message — rather than at apply. A URL
    cite always resolves to a web child (a URL matching a scheme's pattern was
    already rejected in favor of its ``scheme:identifier`` form), and web is
    freeform, so it passes through unchanged.
    """
    if not isinstance(cite_ref, SchemeCitationRef):
        return locator
    source_type = scheme_source_type(cite_ref.scheme)
    try:
        return normalized_locator(source_type, locator)
    except ValidationError as exc:
        raise PatchError(
            f"{ref}: cite locator {locator!r}: "
            f"{'; '.join(exc.message_dict.get('locator', exc.messages))}"
        ) from exc


def _parse_cite_value(cite: str, archive: str, ref: str) -> CitationRef:
    """Parse one non-empty cite spec into a :data:`CitationRef`.

    Shared by the entry-level ``cite:`` (via :func:`_parse_provenance`) and the
    inline ``cites:`` map (:func:`_parse_cites`). Two forms:

    * a ``http(s)://`` URL — a standalone web source; an optional ``archive``
      durable-snapshot URL rides along;
    * ``scheme:identifier`` — the scheme must be a registered scheme and the
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
    if not is_known_scheme(scheme):
        raise PatchError(
            f"{ref}: unknown cite scheme {scheme!r} "
            f"(known: {', '.join(sorted(known_scheme_keys()))})"
        )
    normalized = normalize_scheme_identifier(scheme, raw_id)
    if normalized is None:
        raise PatchError(f"{ref}: invalid {scheme} identifier {raw_id!r}")
    if len(normalized) > CITATION_SOURCE_IDENTIFIER_MAX_LENGTH:
        raise PatchError(
            f"{ref}: cite identifier exceeds "
            f"{CITATION_SOURCE_IDENTIFIER_MAX_LENGTH} characters"
        )
    return SchemeCitationRef(scheme=scheme, identifier=normalized)


def _parse_cite_url(url: str, archive_url: str, ref: str) -> WebCitationRef:
    """Validate a ``http(s)://`` cite URL into a standalone-web CitationRef.

    Rejects a URL that matches a known scheme's record pattern (it has a
    canonical ``scheme:identifier`` form that dedups correctly), a malformed
    URL, and one too long for the link column.
    """
    rec = recognize_scheme(url)
    if rec is not None:
        raise PatchError(
            f"{ref}: cite URL matches the {rec.scheme} scheme — "
            f"cite it as {rec.scheme}:{rec.identifier} instead"
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
    return WebCitationRef(url=url, archive_url=archive_url)
