"""Build structured display values for FK-bearing claim values in edit history.

A relationship claim's stored value is a dict like
``{"person": 13, "role": 9, "exists": true}``, and a direct FK claim's is
the target's bare PK — fine for the data model, unfriendly for users. This
module turns both into a
:class:`~apps.provenance.schemas.ClaimDisplayValueSchema` — an ordered list of
identity parts (each resolved to a user-facing label) and qualifier parts
(scalars left as-is for the frontend to render). A direct FK claim renders as
a single identity part. Layout decisions (separators, ``×N`` count suffixes,
parentheses around categories) live on the frontend; the backend's job is
FK-pk-to-label resolution.

Usage::

    labels = resolve_labels([FieldValue(field_name, value, model), ...])
    bundled = claim_value(model, field_name, value, ctx)  # {raw, display}

``resolve_labels`` queries one row per FK target model (no per-row N+1).
Non-FK scalars (``year``, ``name``, …) and unregistered namespaces return
``None`` — clients fall back to the raw value in that case.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple

import sentry_sdk
from django.core.exceptions import FieldDoesNotExist
from django.db.models import ForeignKey, Model

from apps.core.markdown import (
    WikilinkAuthoringLookup,
    apply_storage_to_authoring,
    get_markdown_fields,
    resolve_wikilink_authoring,
)
from apps.core.types import ClaimFieldName, ClaimValueKey

from .models import ClaimControlledModel
from .schemas import (
    ClaimDisplayIdentityPartSchema,
    ClaimDisplayIdentityState,
    ClaimDisplayQualifierPartSchema,
    ClaimDisplaySchema,
    ClaimDisplayValueSchema,
    ClaimValueSchema,
    MarkdownClaimDisplaySchema,
)
from .types import RelationshipClaimValue
from .validation import (
    MemberSpec,
    RelationshipSchema,
    get_display_override,
    get_relationship_schema,
)

logger = logging.getLogger(__name__)


class _LabelResult(NamedTuple):
    """A resolved identity label plus its state discriminant.

    Two-return-value plumbing for the engine: ``state`` says which case
    we're in, ``label`` carries the resolved string when ``state ==
    "resolved"`` and is None otherwise. The Schema mirrors this shape;
    rendering decisions for the non-resolved states are the frontend's.
    """

    label: str | None
    state: ClaimDisplayIdentityState


class FieldValue(NamedTuple):
    """A claim value paired with the field name and subject model that interpret it.

    The field name picks which relationship schema applies (dict values) or
    which concrete FK field the value is a PK of (int values, introspected on
    ``model``); the value is the raw payload. Callers feed
    :func:`resolve_labels` with these so FK pks can be collected for batched
    resolution.
    """

    field_name: ClaimFieldName
    value: object
    model: type[ClaimControlledModel]


class FkRef(NamedTuple):
    """A reference to a specific row in an FK target model."""

    model: type[Model]
    pk: int


class LabelLookup:
    """Display labels resolved from :class:`FkRef`\\ s.

    Built once per response by :func:`resolve_labels`; consulted by the
    display engine when it needs to turn a pk into a name.
    """

    __slots__ = ("_labels",)

    def __init__(self) -> None:
        self._labels: dict[FkRef, str] = {}

    def add(self, ref: FkRef, label: str) -> None:
        self._labels[ref] = label

    def get(self, ref: FkRef) -> str | None:
        return self._labels.get(ref)


class _DisplayInvariantError(Exception):
    """A claim value reached display in a shape write-time validation forbids."""


def _report_invariant_breach(kind: str, detail: str) -> None:
    """Log the breach and send it to Sentry, degrading the slot instead of raising.

    The exception is never raised, so Sentry groups it on ``kind`` alone; a
    single corrupt ingest must not open one issue per claim. ``detail`` goes to
    the log line, which reaches the event as a breadcrumb.
    """
    logger.error("display: %s: %s", kind, detail)
    sentry_sdk.capture_exception(_DisplayInvariantError(kind))


def _fk_label(
    value: RelationshipClaimValue,
    schema: RelationshipSchema,
    spec: MemberSpec,
    labels: LabelLookup,
) -> _LabelResult:
    """Resolve a member's FK value into a ``_LabelResult``.

    Returns ``(None, "missing")`` when the claim dict carries no value
    for the key — an invariant violation that validation rule 4 should
    prevent (logged loudly so it's observable). Returns ``(None,
    "deleted")`` when the pk is present but the target row no longer
    exists — a legitimate runtime condition. Otherwise returns the
    resolved label with ``state="resolved"``.
    """
    assert spec.fk_target is not None, (
        f"{schema.namespace!r}.{spec.name!r} is not declared as an FK"
    )
    # Display assumes pk lookups. Validation honours ``lookup_field``, so a
    # future ``FkTarget(Model, "slug")`` registration would silently miss
    # labels here. Fail loud until that case is actually needed.
    assert spec.fk_target.lookup_field == "pk", (
        f"{schema.namespace!r}.{spec.name!r} uses non-pk lookup "
        f"{spec.fk_target.lookup_field!r}; display only supports pk"
    )
    pk = value.get(spec.name)
    if pk is None:
        # Write-time validation forbids this shape, so something bypassed it.
        # Degrade the one slot rather than 500 the whole page.
        _report_invariant_breach(
            "missing identity key",
            f"{spec.name!r} in namespace {schema.namespace!r} — validation "
            f"rule 4 should prevent this; value={dict(value)!r}",
        )
        return _LabelResult(label=None, state="missing")
    # ``type(pk) is int`` (not ``isinstance``): ``isinstance(True, int)`` is
    # ``True`` and would let a stray bool slip through as a pk.
    if type(pk) is not int:
        _report_invariant_breach(
            "non-int pk for an identity key",
            f"{pk!r} ({type(pk).__name__}) for {spec.name!r} in namespace "
            f"{schema.namespace!r} — validation rule 5 should prevent this; "
            f"value={dict(value)!r}",
        )
        return _LabelResult(label=None, state="missing")
    label = labels.get(FkRef(spec.fk_target.model, pk))
    if label is None:
        return _LabelResult(label=None, state="deleted")
    return _LabelResult(label=label, state="resolved")


def resolve_member_label(
    value: RelationshipClaimValue,
    schema: RelationshipSchema,
    spec: MemberSpec,
    labels: LabelLookup,
) -> _LabelResult:
    """Resolve one member (primary-part) slot into a ``_LabelResult``.

    Composes :func:`get_display_override` (declarative display_key
    substitution) with :func:`_fk_label` (FK pk → label) and the canonical
    scalar fallback. The override and resolved-scalar paths always return
    ``state="resolved"``; missing-key paths report the breach and return
    ``state="missing"``.
    """
    override = get_display_override(value, spec)
    if override is not None:
        return _LabelResult(label=override, state="resolved")
    if spec.fk_target is not None:
        return _fk_label(value, schema, spec, labels)
    # ``is not None`` (not truthy) so a deliberately empty identity renders
    # as the empty string rather than state="missing".
    raw = value.get(spec.name)
    if raw is None:
        _report_invariant_breach(
            "missing scalar identity key",
            f"{spec.name!r} in namespace {schema.namespace!r} — validation "
            f"rule 4 should prevent this; value={dict(value)!r}",
        )
        return _LabelResult(label=None, state="missing")
    return _LabelResult(label=str(raw), state="resolved")


def _direct_fk_target(
    model: type[ClaimControlledModel], field_name: ClaimFieldName
) -> type[Model] | None:
    """The related model of a concrete FK field on *model*, else ``None``.

    Decides whether an int claim value is a direct FK claim's target PK
    (``MachineModel.display_type = 7``) rather than a plain numeric scalar
    (``year = 1997``).
    """
    try:
        field = model._meta.get_field(field_name)
    except FieldDoesNotExist:
        return None
    if not isinstance(field, ForeignKey):
        return None
    target = field.related_model
    if not isinstance(target, type):
        return None
    return target


def _collect_refs(items: Iterable[FieldValue]) -> set[FkRef]:
    """Walk :class:`FieldValue`\\ s and gather every FK reference.

    Dict values contribute their relationship-schema FK slots; int values
    contribute the direct FK claim's target (when ``field_name`` is a
    concrete FK on the subject model). Other scalars have no FKs to resolve.
    Corrupt pk values (None, wrong type) are skipped silently here;
    ``_fk_label`` is the canonical log site for those violations so we don't
    double-log when the same claim flows through both functions during a
    single response.
    """
    refs: set[FkRef] = set()
    for item in items:
        value = item.value
        if type(value) is int:
            target = _direct_fk_target(item.model, item.field_name)
            if target is not None:
                refs.add(FkRef(target, value))
            continue
        if not isinstance(value, dict):
            continue
        schema = get_relationship_schema(item.field_name)
        if schema is None:
            continue
        # Only members carry fk_target (structurally — PayloadSpec has none).
        for spec in schema.members:
            if spec.fk_target is None:
                continue
            # Display-engine limitation. Same check fires in ``_fk_label``;
            # consider hoisting to ``register_relationship_schema`` if a
            # second site ever needs it.
            assert spec.fk_target.lookup_field == "pk", (
                f"{item.field_name!r}.{spec.name!r} uses non-pk lookup "
                f"{spec.fk_target.lookup_field!r}; display only supports pk"
            )
            pk = value.get(spec.name)
            # Don't crash on data-integrity violations — ``_fk_label`` logs
            # and degrades to ``state="missing"`` for the same row when it
            # processes the value later in the request.
            if type(pk) is not int:
                continue
            refs.add(FkRef(spec.fk_target.model, pk))
    return refs


def resolve_labels(items: Iterable[FieldValue]) -> LabelLookup:
    """Build a :class:`LabelLookup` for all relationship claims in ``items``.

    One query per FK target model. Claim-controlled targets provide their label
    through the model-level ``claim_display_label`` hook; other Django models
    retain the ``str(instance)`` fallback. Missing rows (referent deleted)
    simply don't appear in the result; callers (``_fk_label``) emit
    ``state="deleted"`` for those refs.
    """
    pks_by_model: dict[type[Model], set[int]] = defaultdict(set)
    for ref in _collect_refs(items):
        pks_by_model[ref.model].add(ref.pk)

    lookup = LabelLookup()
    for model, pks in pks_by_model.items():
        if issubclass(model, ClaimControlledModel):
            queryset = model._default_manager.filter(pk__in=pks)
            if model.claim_display_select_related:
                queryset = queryset.select_related(*model.claim_display_select_related)
            for inst in queryset:
                lookup.add(FkRef(model, inst.pk), inst.claim_display_label())
            continue
        for other in model._default_manager.filter(pk__in=pks):
            lookup.add(FkRef(model, other.pk), str(other))
    return lookup


@dataclass(frozen=True)
class ClaimDisplayContext:
    """Pre-resolved references for rendering a batch of claim values.

    Built once per response by :func:`resolve_display_context` so display
    rendering issues no per-row queries: ``labels`` resolves relationship FK
    pks to labels, ``wikilinks`` resolves markdown ``[[type:id:N]]`` markers to
    their authoring keys.
    """

    labels: LabelLookup
    wikilinks: WikilinkAuthoringLookup


def resolve_display_context(items: Iterable[FieldValue]) -> ClaimDisplayContext:
    """Resolve FK labels and wikilink authoring keys for ``items`` in one pass.

    One query per FK target model (via :func:`resolve_labels`) plus one per
    enabled public-id link type (via :func:`resolve_wikilink_authoring`) —
    bounded independent of the number of claims. The wikilink scan reads every
    string value (markers are self-typed, so a non-markdown string simply
    contributes no markers); only :func:`build_display_value` needs the
    per-claim model, to decide whether to emit the markdown rendering.
    """
    materialized = list(items)
    return ClaimDisplayContext(
        labels=resolve_labels(materialized),
        wikilinks=resolve_wikilink_authoring(
            item.value for item in materialized if isinstance(item.value, str)
        ),
    )


def build_display_value(
    model: type[ClaimControlledModel],
    field_name: ClaimFieldName,
    value: object,
    ctx: ClaimDisplayContext,
) -> ClaimDisplaySchema | None:
    """Return the user-facing rendering for a claim value, dispatched by kind.

    Model-driven, four-way dispatch derived from introspection — no
    hardcoded field names:

    - **relationship** — ``field_name`` is a registered relationship
      namespace and ``value`` is its dict payload → structured
      identity/qualifier rendering.
    - **direct FK** — ``field_name`` is a concrete FK on ``model`` and
      ``value`` is its target PK → a single resolved identity part (reusing
      the relationship rendering, so the frontend needs no new case).
    - **markdown** — ``field_name`` is a ``MarkdownField`` on ``model`` and
      ``value`` is a non-empty string → authoring-form text (``[[type:id:N]]``
      resolved to ``[[type:slug]]``).
    - otherwise → ``None``; non-FK scalars and unknown namespaces fall
      through and the frontend renders the raw value.
    """
    if isinstance(value, dict):
        schema = get_relationship_schema(field_name)
        if schema is not None:
            return _build_relationship_display(value, schema, ctx.labels)
    if type(value) is int:
        target = _direct_fk_target(model, field_name)
        if target is not None:
            label = ctx.labels.get(FkRef(target, value))
            return ClaimDisplayValueSchema(
                identity=[
                    ClaimDisplayIdentityPartSchema(
                        key=field_name,
                        label=label,
                        # The claim was validated at write time, so an
                        # unresolvable pk means the target row was since
                        # hard-deleted.
                        state="resolved" if label is not None else "deleted",
                    )
                ],
                qualifiers=[],
            )
    if isinstance(value, str) and value and field_name in get_markdown_fields(model):
        return MarkdownClaimDisplaySchema(
            text=apply_storage_to_authoring(value, ctx.wikilinks)
        )
    return None


def _build_relationship_display(
    value: RelationshipClaimValue, schema: RelationshipSchema, labels: LabelLookup
) -> ClaimDisplayValueSchema:
    """Structured rendering for a relationship-claim value.

    Generic engine: members are the primary parts, emitted in declaration
    order via :func:`resolve_member_label` (the wire field is still named
    ``identity`` — see ``ClaimDisplayValueSchema``); payload specs are
    emitted as ``ClaimDisplayQualifierPartSchema`` entries in declaration
    order, except display_key targets, which a member's rendering consumes.
    Absent qualifier keys are skipped; present-but-falsy qualifiers
    (``None``, ``False``, ``0``, ``""``) are emitted — "should this be
    visible to the user" is the frontend's job.
    """
    # Absent ladder rungs are absence by design, not data violations: an
    # xor_groups namespace sets exactly one group per claim, so the other
    # groups' slots (nullable FK → None, literal → "") are skipped rather
    # than rendered as missing primary parts.
    absent_xor_slots: set[ClaimValueKey] = set()
    if schema.xor_groups is not None:
        absent_xor_slots = {
            name
            for group in schema.xor_groups
            for name in group
            if value.get(name) in (None, "")
        }

    identity_parts: list[ClaimDisplayIdentityPartSchema] = []
    qualifier_parts: list[ClaimDisplayQualifierPartSchema] = []

    for member in schema.members:
        if member.name in absent_xor_slots:
            continue
        result = resolve_member_label(value, schema, member, labels)
        identity_parts.append(
            ClaimDisplayIdentityPartSchema(
                key=member.name,
                label=result.label,
                state=result.state,
            )
        )

    for pspec in schema.payload:
        # display_key targets are consumed by their member's rendering;
        # they must not also surface as qualifiers.
        if pspec.name in schema.display_targets:
            continue
        if pspec.name not in value:
            continue
        raw = value[pspec.name]
        # Pass the typed value through. ``bool`` stays bool through this
        # Python-side path because ``raw`` keeps its runtime type — the
        # Pydantic-side coercion risk (True → 1) is handled at the Schema
        # by ordering ``bool`` before ``int`` in the union. Unexpected
        # types get stringified (schema validation should have caught any).
        scalar: bool | int | str | None = (
            raw if raw is None or isinstance(raw, bool | int | str) else str(raw)
        )
        qualifier_parts.append(
            ClaimDisplayQualifierPartSchema(key=pspec.name, value=scalar)
        )

    return ClaimDisplayValueSchema(identity=identity_parts, qualifiers=qualifier_parts)


def claim_value(
    model: type[ClaimControlledModel],
    field_name: ClaimFieldName,
    value: object,
    ctx: ClaimDisplayContext,
) -> ClaimValueSchema:
    """Bundle a raw claim value with its user-facing display rendering."""
    return ClaimValueSchema(
        raw=value, display=build_display_value(model, field_name, value, ctx)
    )
