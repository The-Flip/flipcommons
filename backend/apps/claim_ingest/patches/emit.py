"""Emit layer: the low-level verbs that build plan rows for one resolved entry.

Given a target already resolved by :mod:`.planning`, append the
``PlannedClaimAssert`` / ``PlannedClaimRetract`` / ``PlannedEntityCreate`` rows
the apply engine later writes, doing the DB reads needed to resolve
FK/relationship targets (``_lookup_*``). Hands its producer-owned result records
— ``_RemovalResult``, ``_MemberEmitResult``, ``_HierarchyEdge`` — back up to
:mod:`.planning`'s cross-entry guards. Called by :mod:`.planning`; depends on
:mod:`._types` and :mod:`.parsing`; never imports :mod:`.planning` (that would
cycle).
"""

from __future__ import annotations

from typing import NamedTuple

from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.claim_ingest.patches._types import (
    ClaimKey,
    PatchError,
    PublicId,
    _Target,
)
from apps.claim_ingest.patches.entity_registry import PatchEntityRegistry
from apps.claim_ingest.patches.parsing import (
    CreateEntry,
    DeleteEntry,
    EditEntry,
    PatchEntry,
)
from apps.claim_ingest.plan import (
    CitationRef,
    CiteHandle,
    Handle,
    IngestPlan,
    Namespace,
    PlannedClaimAssert,
    PlannedClaimRetract,
    PlannedEntityCreate,
)
from apps.core.entity_types import get_linkable_model
from apps.core.models import LIFECYCLE_STATUS_FIELD, LifecycleStatusModel
from apps.core.soft_delete import (
    CascadeBlocker,
    has_lifecycle,
    require_linkable,
    soft_delete_walk,
)
from apps.core.types import EntityKey
from apps.provenance.claim_presence import member_is_present
from apps.provenance.claims import (
    build_relationship_claim,
    normalize_abbreviation_value,
    normalize_alias_identity,
    normalize_fk_value,
)
from apps.provenance.models import (
    Claim,
    IdentityPart,
    LinkableClaimModel,
    Source,
    get_claim_fields,
)
from apps.provenance.validation import get_relationship_schema


class _RemovalResult(NamedTuple):
    """Outcome of ``_add_removals`` for one entry.

    ``removed_members`` is every *intended* removal (claim_key → label), recorded
    for the clash guard regardless of DB state; ``carrier_written`` is whether at
    least one tombstone was actually emitted (a no-op removal writes nothing).
    """

    removed_members: dict[ClaimKey, str]
    carrier_written: bool


class _HierarchyEdge(NamedTuple):
    """A child→parent edge asserted into a self-referential hierarchy.

    Self-referential relationship namespaces (``theme_parent``,
    ``gameplay_feature_parent`` — structurally: a single FK identity whose
    target *is* the subject model) form a DAG. Each ``exists=true`` member is a
    child→parent edge, identified by public_id so same-patch creates (no PK yet)
    and existing rows share one namespace. Collected for the plan-wide acyclicity
    guard that the API enforces but the patch path otherwise bypasses.

    Carries its own ``model_class`` so the edge is self-describing — the
    acyclicity guard groups a flat edge list by model rather than relying on an
    external dict key.
    """

    model_class: type[LinkableClaimModel]
    namespace: Namespace
    child: PublicId
    parent: PublicId
    ref: str  # the entry-ref/handle that asserted the edge, for the error message


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
    by the provenance-carrier check. ``hierarchy_edges`` are the self-referential
    child→parent edges this call asserted (empty for a non-hierarchy namespace),
    returned for the caller to thread into the plan-wide acyclicity guard.
    """

    clash_keys: list[ClaimKey]
    deferred_handles: list[Handle]
    carrier_written: bool
    hierarchy_edges: list[_HierarchyEdge]


def _resolve_model_class(entry: PatchEntry) -> type[LinkableClaimModel]:
    try:
        model_class = get_linkable_model(entry.entity_type)
    except ValueError as exc:
        raise PatchError(f"{entry.ref}: {exc}") from exc
    # A patch may name any addressable claim subject. Today every concrete
    # ``LinkableClaimModel`` is a ``CatalogModel``, so this gate is behaviorally
    # identical to the former ``issubclass(_, CatalogModel)`` — it just no longer
    # names the domain base.
    if not issubclass(model_class, LinkableClaimModel):
        raise PatchError(f"{entry.ref}: {entry.entity_type!r} is not a catalog entity")
    return model_class


def _lookup_pk(target_model: type[models.Model], public_id: str) -> int | None:
    # Canonicalize via the same definition the apply-time resolver uses
    # (str-cast + trim), so a padded value resolves identically at build time
    # and at apply — no build-vs-apply FK drift.
    key = normalize_fk_value(public_id)
    if key is None:
        return None
    pid_field = getattr(target_model, "public_id_field", "slug")
    return (
        target_model._default_manager.filter(**{pid_field: key})
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
    model_class: type[LinkableClaimModel],
    namespace: Namespace,
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
    namespace: Namespace,
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
    model_class: type[LinkableClaimModel],
    namespace: Namespace,
    value: object,
    target: _Target,
    entry: PatchEntry,
    *,
    registry: PatchEntityRegistry,
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
    deferred_handles: list[Handle] = []
    hierarchy_edges: list[_HierarchyEdge] = []
    seen_keys: set[ClaimKey] = set()
    # Deferred members lack a concrete claim_key, so dedup them on the target
    # handle (the namespace is fixed for this call) to keep the same "duplicate
    # member" strictness as the concrete path's seen_keys.
    seen_deferred: set[Handle] = set()
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
            hierarchy_edges.append(
                _HierarchyEdge(
                    model_class=model_class,
                    namespace=namespace,
                    child=entry.public_id,
                    parent=member,
                    ref=entry.ref,
                )
            )
        if isinstance(rel_spec, _FkMemberSpec) and isinstance(member, str):
            handle = registry.created_handle(
                rel_spec.target_model, normalize_fk_value(member)
            )
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
        hierarchy_edges=hierarchy_edges,
    )


def _add_removals(
    plan: IngestPlan,
    model_class: type[LinkableClaimModel],
    existing: LinkableClaimModel,
    entry: EditEntry,
    ct_id: int,
    source: Source,
    rel_namespaces: frozenset[Namespace],
    rel_fields_by_model: dict[type[LinkableClaimModel], set[str]],
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

    True only when the source's current claim for *claim_key* asserts presence —
    so an already-removed (``exists=false``) or never-claimed member reads as
    absent, and removing it would be an inert no-op.

    The presence/tombstone semantics are the single definition in
    :func:`~apps.provenance.claim_presence.member_is_present`; this wraps it
    with the source-scoped selection (``.first()`` is the source's current claim,
    given the one-active-claim-per-(source, claim_key) invariant).
    """
    claim = Claim.objects.filter(
        source=source,
        is_active=True,
        content_type_id=ct_id,
        object_id=object_id,
        claim_key=claim_key,
    ).first()
    return member_is_present(claim)


def _add_create(
    plan: IngestPlan,
    model_class: type[LinkableClaimModel],
    entry: CreateEntry,
    handle: Handle,
    *,
    registry: PatchEntityRegistry,
    note: str = "",
) -> None:
    """Emit a ``PlannedEntityCreate`` plus its required identity/status claims.

    The author writes only the authored fields; the adapter supplies the
    public_id (from the entry key) and, for a lifecycle-bearing target,
    ``status='active'``, and feeds every claim-controlled kwarg into both the
    create kwargs *and* a matching assertion (the engine's create contract).
    Authored field assertions are emitted by the caller's field loop.

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
    # reference, and — for a lifecycle-bearing target — status is always
    # 'active'. Authoring either would spawn an entity that doesn't match its
    # reference or trip the engine's create contract, so reject. The form field
    # itself (slug) stays author-writable on a derived create — only the derived
    # public id field is off-limits. (Status is adapter-owned only when present;
    # lifecycle is a discovered capability — see the ``status`` stamp below.)
    adapter_owned_fields = {pid_field}
    if has_lifecycle(model_class):
        adapter_owned_fields.add(LIFECYCLE_STATUS_FIELD)
    adapter_owned = adapter_owned_fields & entry.fields.keys()
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
    # The claim-controlled lifecycle field (``LifecycleStatusModel.status``) is
    # never written by a patch as a free-form claim: a create sets it to
    # ``active`` here, and a soft-delete transitions it to ``deleted`` via the
    # ``delete:`` directive (which routes through the soft-delete planner). A raw
    # claim would skip that planner's safety checks — so :mod:`.planning` rejects
    # any ``status`` field key before it reaches here.
    #
    # Lifecycle is a discovered capability (see ``LinkableClaimModel``): a target
    # without ``LifecycleStatusModel`` has no ``status`` field, so the stamp and
    # its paired assertion (below) are both omitted. They must stay in lockstep —
    # the apply layer requires every claim-controlled create kwarg to have a
    # matching assertion.
    kwargs: dict[str, object] = {pid_field: entry.public_id}
    if has_lifecycle(model_class):
        kwargs[LIFECYCLE_STATUS_FIELD] = "active"
    # FK columns whose target is created earlier in this same patch: deferred to
    # the target handle's PK by the apply layer (resolved after the bulk-create).
    # The field loop still emits the concrete provenance claim, which
    # _validate_entity_claim_consistency pairs with this handle_ref.
    handle_refs: dict[str, Handle] = {}

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
                ref_handle = registry.created_handle(
                    target_model, normalize_fk_value(value)
                )
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
    # Paired with the ``status`` create kwarg above — emitted only for a
    # lifecycle-bearing target (the two must stay in lockstep).
    if has_lifecycle(model_class):
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
    existing: LinkableClaimModel,
    entry: DeleteEntry,
    *,
    note: str = "",
    citation_ref: CitationRef | None = None,
) -> list[EntityKey]:
    """Emit ``status=deleted`` assertions to soft-delete *existing* and its cascade.

    A patch delete is a ``status=deleted`` claim, exactly like the in-app
    delete — no row removal. It reuses the generic
    :func:`apps.core.soft_delete.soft_delete_walk` so it obeys the same
    record-lifecycle rules: it **refuses** when an active PROTECT
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
    # Soft-delete is a lifecycle operation. Lifecycle is a discovered capability
    # (see ``LinkableClaimModel``): a target without ``LifecycleStatusModel`` is
    # create/edit-patchable but not deletable, so ``delete:`` is the one
    # directive that rejects it. (Every concrete target is a ``CatalogModel``
    # today, but the contract holds for a future lower-capability model.)
    if not isinstance(existing, LifecycleStatusModel):
        raise PatchError(
            f"{entry.ref}: {entry.entity_type!r} has no lifecycle and cannot be deleted"
        )
    walk = soft_delete_walk(existing)
    if walk.blockers:
        blockers = "; ".join(_format_blocker(b) for b in walk.blockers)
        raise PatchError(
            f"{entry.ref}: cannot delete — still referenced by "
            f"{len(walk.blockers)} active entity(ies): {blockers}. Reassign or "
            f"delete the referrer first (in an earlier patch)."
        )
    affected: list[EntityKey] = []
    for target_entity in walk.cascade:
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
    cascaded = [require_linkable(e) for e in walk.cascade if e.pk != existing.pk]
    if cascaded:
        members = ", ".join(f"{e.entity_type}.{e.public_id}" for e in cascaded)
        plan.warnings.append(
            f"{entry.ref}: delete cascades to {len(cascaded)} child entity(ies): {members}"
        )
    return affected


def _format_blocker(blocker: CascadeBlocker) -> str:
    """Render one core :class:`CascadeBlocker` for the delete-refusal message.

    Narrows the referrer to ``LinkableModel`` for its canonical ``entity_type``,
    falling back to ``str(referrer)`` when it has no ``slug``.
    """
    ref = require_linkable(blocker.referrer)
    slug = getattr(ref, "slug", None)
    return f"{ref.entity_type} {(slug or str(ref))!r} (via {blocker.relation})"


def _add_retractions(
    plan: IngestPlan,
    model_class: type[LinkableClaimModel],
    existing: LinkableClaimModel,
    entry: EditEntry,
    ct_id: int,
    source: Source,
    rel_namespaces: frozenset[Namespace],
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
