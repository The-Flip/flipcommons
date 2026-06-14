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

from apps.catalog.ingestion.patches._types import PatchError
from apps.catalog.ingestion.plan import CitationRef, CiteHandle
from apps.citation.extractors import EXTRACTORS
from apps.citation.models import (
    CITATION_SOURCE_IDENTIFIER_MAX_LENGTH,
    CITATION_SOURCE_LINK_URL_MAX_LENGTH,
)
from apps.citation.seed_data.types import SeedLink, SeedSource
from apps.core.types import JsonBody
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
RESERVED_FIELD_KEYS = frozenset(
    {"create", "delete", "expect", "retract", "remove", "note", "cite", "cites"}
)

# Allowed keys in a `sources:` node / its links, derived from the seed TypedDicts
# (the single source of truth). `children` is excluded — v1 sources are flat.
ALLOWED_SOURCE_KEYS = frozenset(SeedSource.__annotations__) - {"children"}
ALLOWED_LINK_KEYS = frozenset(SeedLink.__annotations__)


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
