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
from dataclasses import dataclass
from typing import NamedTuple

import yaml
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.catalog.claims import build_relationship_claim, get_relationship_namespaces
from apps.catalog.ingestion.apply import (
    CitationRef,
    IngestPlan,
    PlannedClaimAssert,
    PlannedClaimRetract,
    PlannedEntityCreate,
)
from apps.catalog.models import CatalogModel
from apps.catalog.resolve import resolve_relationships_bulk
from apps.citation.extractors import EXTRACTORS
from apps.citation.models import CITATION_SOURCE_IDENTIFIER_MAX_LENGTH
from apps.core.entity_types import get_linkable_model
from apps.core.types import JsonBody
from apps.provenance.models import Source, get_claim_fields
from apps.provenance.models.changeset import CHANGESET_NOTE_MAX_LENGTH
from apps.provenance.validation import get_relationship_schema

PATCH_ID_RE = re.compile(r"^\d{4}-[a-z0-9-]+$")

# Keys in a claim entry's value mapping that are directives, not claim fields.
RESERVED_FIELD_KEYS = frozenset({"create", "expect", "retract", "note", "cite"})


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


@dataclass(frozen=True)
class PatchClaim:
    """One claim entry: an entity reference plus the fields to assert."""

    entity_type: str
    public_id: str
    create: bool
    expect: JsonBody
    retract: list[str]
    fields: JsonBody
    # Per-entry provenance. ``note`` becomes the entity's ChangeSet note;
    # ``cite`` is a raw ``scheme:identifier`` string, parsed + validated into a
    # CitationRef in build_plan. Empty string when the entry sets neither.
    note: str = ""
    cite: str = ""

    @property
    def ref(self) -> str:
        return f"{self.entity_type}.{self.public_id}"


@dataclass(frozen=True)
class PatchDoc:
    """A fully-parsed, structurally-valid patch (no DB access yet)."""

    attribution: str
    description: str
    claims: list[PatchClaim]
    fingerprint: str


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

    raw_claims = data.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise PatchError("'claims' is required and must be a non-empty list")

    claims: list[PatchClaim] = []
    for i, entry in enumerate(raw_claims):
        if not isinstance(entry, dict) or len(entry) != 1:
            raise PatchError(
                f"claims[{i}] must be a single-key mapping (entity ref → fields)"
            )
        ((ref, raw_fields),) = entry.items()
        if not isinstance(ref, str) or "." not in ref:
            raise PatchError(f"claims[{i}] key {ref!r} must be 'type.public_id'")
        entity_type, public_id = ref.split(".", 1)
        if not entity_type or not public_id:
            raise PatchError(f"claims[{i}] key {ref!r} must be 'type.public_id'")
        if not isinstance(raw_fields, dict):
            raise PatchError(f"claims[{i}] ({ref}) value must be a mapping")

        raw_create = raw_fields.get("create", False)
        if not isinstance(raw_create, bool):
            raise PatchError(f"{ref}: 'create' must be a boolean")
        raw_expect = raw_fields.get("expect", {})
        if not isinstance(raw_expect, dict):
            raise PatchError(f"{ref}: 'expect' must be a mapping")
        raw_retract = raw_fields.get("retract", [])
        if not isinstance(raw_retract, list) or not all(
            isinstance(f, str) for f in raw_retract
        ):
            raise PatchError(f"{ref}: 'retract' must be a list of field names")
        raw_note = raw_fields.get("note", "")
        if not isinstance(raw_note, str):
            raise PatchError(f"{ref}: 'note' must be a string")
        raw_cite = raw_fields.get("cite", "")
        if not isinstance(raw_cite, str):
            raise PatchError(f"{ref}: 'cite' must be a 'scheme:identifier' string")

        fields = {k: v for k, v in raw_fields.items() if k not in RESERVED_FIELD_KEYS}
        claims.append(
            PatchClaim(
                entity_type=entity_type,
                public_id=public_id,
                create=raw_create,
                expect=raw_expect,
                retract=raw_retract,
                fields=fields,
                note=raw_note,
                cite=raw_cite,
            )
        )

    return PatchDoc(
        attribution=attribution,
        description=description,
        claims=claims,
        fingerprint=fp,
    )


# ---------------------------------------------------------------------------
# Adapter: PatchDoc → IngestPlan
# ---------------------------------------------------------------------------


class _Target(NamedTuple):
    """Where a claim assertion lands: an existing entity or a planned handle."""

    content_type_id: int | None = None
    object_id: int | None = None
    handle: str | None = None


def _parse_provenance(pc: PatchClaim) -> tuple[str, CitationRef | None]:
    """Validate an entry's ``note``/``cite`` and parse ``cite`` into a CitationRef.

    Length-checks each value against the DB column it lands in so an overlong
    value fails as a clear :class:`PatchError` here rather than deep in
    persistence. ``cite`` is a ``scheme:identifier`` string whose scheme must
    be a known extractor and whose identifier must normalize.
    """
    note = pc.note
    if len(note) > CHANGESET_NOTE_MAX_LENGTH:
        raise PatchError(
            f"{pc.ref}: note exceeds {CHANGESET_NOTE_MAX_LENGTH} characters"
        )
    if not pc.cite:
        return note, None
    scheme, sep, raw_id = pc.cite.partition(":")
    if not sep or not scheme or not raw_id:
        raise PatchError(
            f"{pc.ref}: cite {pc.cite!r} must be 'scheme:identifier' (e.g. 'ipdb:4443')"
        )
    extractor = EXTRACTORS.get(scheme)
    if extractor is None:
        raise PatchError(
            f"{pc.ref}: unknown cite scheme {scheme!r} "
            f"(known: {', '.join(sorted(EXTRACTORS))})"
        )
    normalized = extractor.normalize(raw_id)
    if normalized is None:
        raise PatchError(f"{pc.ref}: invalid {scheme} identifier {raw_id!r}")
    if len(normalized) > CITATION_SOURCE_IDENTIFIER_MAX_LENGTH:
        raise PatchError(
            f"{pc.ref}: cite identifier exceeds "
            f"{CITATION_SOURCE_IDENTIFIER_MAX_LENGTH} characters"
        )
    return note, CitationRef(scheme=scheme, identifier=normalized)


def build_plan(doc: PatchDoc, *, source: Source, patch_id: str) -> IngestPlan:
    """Compile a parsed patch into an :class:`IngestPlan`.

    Resolves entity references, runs the ``expect:`` drift guard (scalar +
    FK), emits ``retract:`` directives, classifies each field as scalar / FK /
    relationship by introspection and emits creates + claim assertions. All DB
    reads happen here, before any write; ``apply_plan(plan)`` does the writing.
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
    # Per-target (existing entity) accumulators for the plan-wide retract/assert
    # conflict check below. Keyed by (content_type_id, object_id).
    retracted_fields: dict[tuple[int, int], set[str]] = defaultdict(set)
    asserted_fields: dict[tuple[int, int], set[str]] = defaultdict(set)
    target_ref: dict[tuple[int, int], str] = {}
    # Provenance guard: an entity's claims all collapse into one ChangeSet, so
    # two entries resolving to the same existing entity can't carry independent
    # notes/cites. Track entry count and whether any carried provenance.
    entity_entry_count: dict[tuple[int, int], int] = defaultdict(int)
    entity_has_provenance: dict[tuple[int, int], bool] = defaultdict(bool)
    # Refs already created in this patch. A second create for the same ref would
    # mint a duplicate handle and blow up as a ValueError deep in the apply layer
    # (which the command doesn't catch); reject it cleanly here.
    created_refs: set[str] = set()
    matched = 0

    for pc in doc.claims:
        note, citation_ref = _parse_provenance(pc)
        model_class = _resolve_model_class(pc)
        ct_id = ContentType.objects.get_for_model(model_class).pk
        existing = _lookup_entity(model_class, pc.public_id)

        target: _Target
        if pc.create:
            if existing is not None:
                raise PatchError(
                    f"{pc.ref}: create:true but a {pc.entity_type} with this "
                    f"public_id already exists"
                )
            if pc.ref in created_refs:
                raise PatchError(f"{pc.ref}: duplicate create entry in this patch")
            created_refs.add(pc.ref)
            if pc.expect:
                raise PatchError(f"{pc.ref}: 'expect' is meaningless on a create")
            if pc.retract:
                raise PatchError(f"{pc.ref}: 'retract' is meaningless on a create")
            handle = pc.ref
            _add_create(plan, model_class, pc, handle, note=note)
            target = _Target(handle=handle)
        else:
            if existing is None:
                raise PatchError(
                    f"{pc.ref}: no such {pc.entity_type} (add create:true to create it)"
                )
            matched += 1
            _check_expect(model_class, existing, pc)
            _add_retractions(
                plan, model_class, existing, pc, ct_id, rel_namespaces, note=note
            )
            target = _Target(content_type_id=ct_id, object_id=existing.pk)
            tkey = (ct_id, existing.pk)
            target_ref[tkey] = pc.ref
            retracted_fields[tkey].update(pc.retract)
            entity_entry_count[tkey] += 1
            if note or citation_ref is not None:
                entity_has_provenance[tkey] = True

        claim_fields = get_claim_fields(model_class)
        # Count authored-field assertions actually emitted below, so provenance
        # can be validated against real carriers — a field *key* isn't enough
        # (``tag: []`` emits zero member claims).
        assertions_before = len(plan.assertions)
        for key, value in pc.fields.items():
            if key in claim_fields:
                _emit_direct(
                    plan, key, value, target, note=note, citation_ref=citation_ref
                )
                if target.object_id is not None:
                    asserted_fields[(ct_id, target.object_id)].add(key)
            elif key in rel_namespaces:
                _emit_relationship(
                    plan,
                    model_class,
                    key,
                    value,
                    target,
                    pc,
                    note=note,
                    citation_ref=citation_ref,
                )
                rel_fields_by_model[model_class].add(key)
            else:
                raise PatchError(f"{pc.ref}: unknown field {key!r}")

        # Provenance needs an emitted carrier, or it would silently vanish.
        # ``cite`` rides an authored field assertion; ``note`` also rides a
        # create's scaffolding claims or a retraction.
        authored_emitted = len(plan.assertions) > assertions_before
        if citation_ref is not None and not authored_emitted:
            raise PatchError(
                f"{pc.ref}: cite has no field to attach to — cite a field you're "
                f"also asserting (a retraction, a field-less create, or an empty "
                f"relationship like 'tag: []' can't carry one)"
            )
        if note and not (authored_emitted or pc.create or pc.retract):
            raise PatchError(
                f"{pc.ref}: note has nothing to attach to — the entry must assert "
                f"a field, retract, or create something"
            )

    plan.records_matched = matched

    # Provenance guard: reject when two entries land on one existing entity and
    # either carries note/cite — their notes would collide in the shared
    # ChangeSet and their cites would be ambiguous. One provenance-bearing entry
    # per entity (combine retract + assert + note + cite into a single entry).
    for tkey, count in entity_entry_count.items():
        if count > 1 and entity_has_provenance[tkey]:
            raise PatchError(
                f"{target_ref[tkey]}: multiple entries target this entity and at "
                f"least one carries note/cite — combine them into one entry "
                f"(an entity's claims share a single changeset)"
            )

    # Plan-wide guard: the same source must not both retract and assert a field
    # on one entity, even across separate entries. The retract only deactivates
    # the pre-existing claim while the assert writes a new one, so the assert
    # silently wins and the retract is a no-op — reject the contradiction.
    for tkey, r_fields in retracted_fields.items():
        both = sorted(r_fields & asserted_fields.get(tkey, set()))
        if both:
            raise PatchError(
                f"{target_ref[tkey]}: cannot both retract and assert "
                f"{', '.join(both)} for this entity"
            )

    # Relationship resolution: delegate to the canonical post-mutation
    # dispatch (model-driven; no hand-maintained namespace→resolver map). The
    # engine resolves scalar/FK itself; these hooks cover the relationships.
    for rel_model, field_names in rel_fields_by_model.items():
        rel_ct_id = ContentType.objects.get_for_model(rel_model).pk
        plan.resolve_hooks.setdefault(rel_ct_id, []).append(
            _make_resolve_hook(rel_model, sorted(field_names))
        )

    return plan


def _resolve_model_class(pc: PatchClaim) -> type[CatalogModel]:
    try:
        model_class = get_linkable_model(pc.entity_type)
    except ValueError as exc:
        raise PatchError(f"{pc.ref}: {exc}") from exc
    if not issubclass(model_class, CatalogModel):
        raise PatchError(f"{pc.ref}: {pc.entity_type!r} is not a catalog entity")
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


def _emit_relationship(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    namespace: str,
    value: object,
    target: _Target,
    pc: PatchClaim,
    *,
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> None:
    schema = get_relationship_schema(namespace)
    if schema is None:
        raise PatchError(f"{pc.ref}: no relationship schema for {namespace!r}")
    if model_class not in schema.valid_subjects:
        raise PatchError(
            f"{pc.ref}: relationship {namespace!r} is not valid on "
            f"{model_class.__name__}"
        )
    identity_specs = [s for s in schema.value_keys if s.identity is not None]
    if len(identity_specs) != 1 or identity_specs[0].fk_target is None:
        raise PatchError(
            f"{pc.ref}: relationship {namespace!r} is not a single-FK "
            f"relationship (unsupported in v1)"
        )
    spec = identity_specs[0]
    assert spec.fk_target is not None  # guarded above
    target_model = spec.fk_target.model
    if not isinstance(value, list):
        raise PatchError(
            f"{pc.ref}: relationship {namespace!r} value must be a list of public_ids"
        )
    for member in value:
        if not isinstance(member, str):
            raise PatchError(
                f"{pc.ref}: relationship {namespace!r} member {member!r} "
                f"must be a public_id string"
            )
        member_pk = _lookup_pk(target_model, member)
        if member_pk is None:
            raise PatchError(
                f"{pc.ref}: relationship {namespace!r} member {member!r} "
                f"does not resolve to a {target_model.__name__}"
            )
        claim_key, claim_value = build_relationship_claim(
            namespace, {spec.name: member_pk}
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


def _add_create(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    pc: PatchClaim,
    handle: str,
    *,
    note: str = "",
) -> None:
    """Emit a ``PlannedEntityCreate`` plus its required slug/status claims.

    The author writes only the authored fields; the adapter supplies the
    public_id (from the entry key) and ``status='active'``, and feeds every
    claim-controlled kwarg into both the create kwargs *and* a matching
    assertion (the engine's create contract). Authored field assertions are
    emitted by the caller's field loop.

    ``note`` rides the adapter-owned slug/status assertions so a create-only
    entry's note still reaches its ChangeSet. A ``cite:`` deliberately does
    *not* — the derived slug and the record-lifecycle status aren't sourced
    facts; the citation rides the authored field claims (the field loop) only.
    """
    pid_field = model_class.public_id_field
    claim_fields = get_claim_fields(model_class)
    # Can't create an entity whose public identity is system-generated rather
    # than claim-based (e.g. Location.location_path, derived from parent +
    # slug): there's no claim to assert it and its value can't come from the
    # entity reference. Reject here rather than fail deep in claim validation.
    # Model-driven: the test is "is public_id_field claim-controlled?", not a
    # hardcoded entity check.
    if pid_field not in claim_fields:
        raise PatchError(
            f"{pc.ref}: creating a {pc.entity_type} is not supported — its "
            f"public id ({pid_field}) is system-generated, not claim-based"
        )
    # These are adapter-owned on a create: the public_id comes from the entity
    # reference and status is always 'active'. Authoring them would either
    # spawn an entity that doesn't match its reference (a different slug) or
    # trip the engine's create contract (status must be 'active'), so reject.
    adapter_owned = {pid_field, "status"} & pc.fields.keys()
    if adapter_owned:
        raise PatchError(
            f"{pc.ref}: do not set {', '.join(sorted(adapter_owned))} on a create "
            f"— the public_id comes from the entity reference and status is "
            f"always 'active'"
        )
    kwargs: dict[str, object] = {pid_field: pc.public_id, "status": "active"}

    for key, value in pc.fields.items():
        if key not in claim_fields:
            continue  # relationships are not model kwargs; emitted as claims
        django_field = model_class._meta.get_field(key)
        if isinstance(django_field, models.ForeignKey):
            target_model = django_field.related_model
            assert isinstance(target_model, type)  # resolved FK target
            if not isinstance(value, str):
                raise PatchError(f"{pc.ref}: FK {key!r} value must be a public_id")
            target_pk = _lookup_pk(target_model, value)
            if target_pk is None:
                raise PatchError(
                    f"{pc.ref}: FK {key!r} target {value!r} does not exist "
                    f"(creating an FK target in the same patch is unsupported)"
                )
            kwargs[django_field.attname] = target_pk
        else:
            kwargs[key] = value

    plan.entities.append(
        PlannedEntityCreate(model_class=model_class, kwargs=kwargs, handle=handle)
    )
    # slug + status are not in pc.fields, so emit their assertions here.
    plan.assertions.append(
        PlannedClaimAssert(
            field_name=pid_field, value=pc.public_id, handle=handle, note=note
        )
    )
    plan.assertions.append(
        PlannedClaimAssert(
            field_name="status", value="active", handle=handle, note=note
        )
    )


def _check_expect(
    model_class: type[CatalogModel],
    entity: CatalogModel,
    pc: PatchClaim,
) -> None:
    """Drift guard: every ``expect:`` value must equal the resolved value.

    Piggybacks the entity already loaded for the claim target — no extra
    query for scalars, one related access for FKs. v1 covers scalar + FK;
    relationship-``expect`` is unsupported.
    """
    if not pc.expect:
        return
    claim_fields = get_claim_fields(model_class)
    for field_name, expected in pc.expect.items():
        if field_name not in claim_fields:
            raise PatchError(
                f"{pc.ref}: expect field {field_name!r} is not a scalar/FK field "
                f"(relationship-expect is unsupported in v1)"
            )
        django_field = model_class._meta.get_field(field_name)
        if isinstance(django_field, models.ForeignKey):
            related = getattr(entity, field_name)
            if related is None:
                actual: object = None
            else:
                pid_field = getattr(type(related), "public_id_field", "slug")
                actual = getattr(related, pid_field)
        else:
            actual = getattr(entity, field_name)
        if actual != expected:
            raise PatchError(
                f"{pc.ref}: expect {field_name}={expected!r} but the resolved "
                f"value is {actual!r}"
            )


def _add_retractions(
    plan: IngestPlan,
    model_class: type[CatalogModel],
    entity: CatalogModel,
    pc: PatchClaim,
    ct_id: int,
    rel_namespaces: frozenset[str],
    *,
    note: str = "",
) -> None:
    """Emit a ``PlannedClaimRetract`` per ``retract:`` field.

    v1 covers scalar/FK fields only, where the claim key equals the field
    name (so the engine's identity match finds the active claim). Relationship
    retract is deferred. Each field must be a scalar/FK claim field on the
    (existing) entity; the engine deactivates *this source's* active claim for
    that key, warning (not erroring) if none is present — so a re-run is a
    no-op.
    """
    if not pc.retract:
        return
    # Note: retract/assert conflicts (same field retracted and asserted on this
    # entity, in this or another entry) are caught plan-wide in build_plan.
    claim_fields = get_claim_fields(model_class)
    for field_name in pc.retract:
        if field_name in rel_namespaces:
            raise PatchError(
                f"{pc.ref}: cannot retract relationship {field_name!r} "
                f"(relationship retract is unsupported in v1)"
            )
        if field_name not in claim_fields:
            raise PatchError(
                f"{pc.ref}: cannot retract {field_name!r} — not a scalar/FK claim "
                f"field on {model_class.__name__}"
            )
        plan.retractions.append(
            PlannedClaimRetract(
                content_type_id=ct_id,
                object_id=entity.pk,
                claim_key=field_name,
                note=note,
            )
        )


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
