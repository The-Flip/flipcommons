"""Plan data types: the declarative carriers an ingest source hands the engine.

These are the public contract between the source front end (``ingestion.patches``)
and the source-agnostic apply engine in :mod:`apps.claim_ingest.apply`. A
front end builds an :class:`IngestPlan` out of these primitives; ``apply_plan``
consumes it. The types live here, apart from the engine, so a front end can
import the carriers without pulling in the engine's machinery — the apply layer
imports *these*, never the reverse.

In compiler terms the :class:`IngestPlan` is the **intermediate representation**:
the source front end *lowers* its input to this one typed instruction list, and
the apply back end is the only thing that turns it into database writes. That
IR boundary is what keeps the engine source-agnostic — keep new behavior on the
front-end/IR side rather than forking ``apply_plan``.

The hook Protocols and the ``RunReport`` result type live here too: they're
named in the plan's own fields and in ``apply_plan``'s signature. The engine's
intermediate carriers (``RetractEntry``, the per-entry provenance maps) stay in
the engine — they're apply-time mechanics, not part of this contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apps.core.types import ClaimValueKey, ContentTypeId, LicenseId
from apps.provenance.models import ClaimControlledModel, Source


class PreWriteHook(Protocol):
    """A side write run first inside the apply transaction, before any claim.

    Registered in ``IngestPlan.pre_write_hooks`` and handed the run's
    ``RunReport`` so it can append warnings and bump audit counters. Today only
    the data-patch adapter uses it (to additively get-or-create citation sources
    a patch's ``sources:`` block declares); the apply layer stays source-agnostic
    by treating the hook as opaque.
    """

    def __call__(self, report: RunReport) -> None: ...


class DryRunPreviewHook(Protocol):
    """A read-only check run on the **dry-run** path, surfacing a state conflict.

    Registered in ``IngestPlan.dry_run_preview_hooks`` and handed the run's
    ``RunReport`` so it can append warnings. The live path runs ``pre_write_hooks``
    instead, so neither path double-warns. Today only the data-patch adapter uses
    it — previewing, at ``--dry-run``, a ``sources:`` node whose recognition hosts
    already span >1 root (a whole-node skip the live upsert would warn on at
    apply). Committed-state-only and writes nothing; the apply layer treats it as
    opaque.
    """

    def __call__(self, report: RunReport) -> None: ...


@dataclass(frozen=True)
class WebCitationRef:
    """The url form of a :data:`CitationRef`.

    ``url`` is a raw web-page URL for a standalone web source, resolved to a
    ``CitationSource`` at apply time via ``get_or_create_web_source`` (no DB
    access to construct one). An optional ``archive_url`` (e.g. a Wayback
    permalink) rides along as a second ``archive``-typed link on the same child
    source, so one citation carries both the live page and its durable snapshot
    — it lives only on this form.
    """

    url: str
    archive_url: str = ""


@dataclass(frozen=True)
class SchemeCitationRef:
    """The scheme form of a :data:`CitationRef`.

    ``scheme`` is a registered ``apps.citation.citation_types`` scheme key (e.g.
    ``"ipdb"``) and ``identifier`` is the normalized in-scheme id (e.g.
    ``"4443"``); resolved to a ``CitationSource`` at apply time via
    ``get_or_create_external_source`` (no DB access to construct one).
    """

    scheme: str
    identifier: str


# A parsed, normalized reference to a citation source: one of two
# mutually-exclusive forms, resolved to a ``CitationSource`` at apply time. A
# sum type so a both-set / neither-set ref is unconstructable and the apply-side
# resolve can ``match`` the variant the builder chose rather than re-reading a
# field. Aliased ``CitationRef`` because most users (``IngestPlan`` fields, the
# emit/planning carriers, the resolve cache key) treat it opaquely.
#
# Defined here, beside the plan dataclasses, rather than in any source adapter:
# the source-agnostic apply layer must not import an adapter, and adapters (e.g.
# ``ingestion.patches``) already import the plan carriers from this module.
type CitationRef = WebCitationRef | SchemeCitationRef


@dataclass(frozen=True)
class CiteSpec:
    """A parsed cite spec: the source ref plus per-instance fields.

    ``ref`` identifies the *source* (and is what the apply-side source
    resolution memoizes on); ``locator`` and ``quote`` are fields of the
    ``CitationInstance`` minted from it — where in the source, and the verbatim
    excerpt. Carried by both the entry-level ``cite:`` and each inline
    footnote in a ``cites:`` map.
    """

    ref: CitationRef
    locator: str = ""
    quote: str = ""


# A patch-local citation handle: the ephemeral label wiring a ``[[cite:N]]``
# authoring marker to its ``cites:`` source spec. A transparent alias of ``str``
# (like the adapter's ``ClaimKey``/``PublicId``) that names the role where a bare
# ``str`` key would otherwise be ambiguous — notably the inner key of the patch
# adapter's field→handle→ref map. All-digits while authoring (``"1"``); rewritten
# to a ``CitationInstance.slug`` at mint, so it never reaches storage.
type CiteHandle = str

# A patch entry's file-order index — the grouping unit for per-entry ChangeSets.
# A transparent alias of ``int`` (like ``CiteHandle`` above) that names the role
# wherever it recurs — on the plan carriers here and in the engine's per-entry
# provenance maps — so a bare ``int`` ordinal isn't mistaken for a pk or count.
# Typed ``| None`` on the carriers only because the front end stamps it in a
# second pass (see ``planning.build_plan``); it is always set by apply time.
type EntryIndex = int

# A plan-local temporary identifier for a not-yet-created entity — the label a
# ``PlannedClaimAssert`` (or another create's ``handle_refs``) uses to point at a
# ``PlannedEntityCreate`` before it has a PK, resolved to an ``EntityKey`` once the
# entity is bulk-created. A transparent alias of ``str`` (like ``CiteHandle``
# above) that names the role wherever a bare ``str`` — a handle-map key, an
# FK/identity-ref value, the adapter's same-patch-create registry value — would
# otherwise be indistinguishable from a public_id or a field name. Used across the
# contract here, the apply engine and the patch adapter.
type Handle = str

# A relationship's namespace — the schema key naming a relationship kind
# (``"location"``, ``"theme_parent"``, ``"credit"``) that a deferred
# ``PlannedClaimAssert`` carries and ``build_relationship_claim`` keys off. A
# transparent alias of ``str`` (like ``Handle`` above) that distinguishes a
# namespace from the other ``str``s it travels with (a handle, a field name, a
# public_id) where the distinction is otherwise invisible — e.g. a
# ``frozenset[str]`` of valid namespaces.
type Namespace = str

# Per-content-type set of relationship namespaces a plan touched, keyed by the
# affected entity's ``ContentTypeId``. The apply engine's ``_resolve`` hands each
# set to the provenance bulk resolver to scope the relationship re-resolution pass
# (scalars/FKs re-resolve regardless). Namespaces only — never scalar field names.
type ChangedRelationshipFields = dict[ContentTypeId, frozenset[Namespace]]


@dataclass
class PlannedEntityCreate:
    """A new catalog entity to be created inside the apply transaction.

    ``handle`` is a temporary identifier used by ``PlannedClaimAssert``
    to reference this entity before it has a PK.  Handles must be unique
    within a plan.

    ``handle_refs`` maps kwarg names to handles of other planned entities.
    After the referenced entity is created, the framework patches the
    kwarg to the created entity's PK.  This solves cross-entity FK
    dependencies (e.g. CorporateEntity needs ``manufacturer_id`` from a
    planned Manufacturer).  Entities must appear in the list **after**
    anything they reference — the adapter controls ordering.
    """

    model_class: type[ClaimControlledModel]
    # kwargs are spread into ``model_class(**kwargs)`` — schema varies per
    # model class, so the value type is genuinely heterogeneous.
    kwargs: dict[str, Any]
    handle: Handle
    # attname (FK column) → the handle of the planned entity supplying its PK.
    handle_refs: dict[str, Handle] = field(default_factory=dict)


@dataclass
class PlannedClaimAssert:
    """A claim to assert about a catalog entity.

    Must target exactly one of:
    - An existing entity: set ``content_type_id`` and ``object_id``.
    - A planned entity: set ``handle`` (matching a ``PlannedEntityCreate``).

    Relationship claim identity uses exactly one of:
    - ``claim_key`` + ``value`` — fully concrete (adapter calls
      ``build_relationship_claim()`` itself).
    - ``relationship_namespace`` + ``identity`` + ``identity_refs`` —
      deferred.  The apply layer resolves handles in ``identity_refs``
      to real PKs, then calls ``build_relationship_claim()`` to generate
      both ``claim_key`` and ``value`` in sync.  This avoids the two
      getting out of sync when relationship identity includes entities
      created in the same plan.
    """

    field_name: str
    # ``value`` is the raw JSONField payload — scalar, dict, list, or null;
    # genuinely arbitrary, so the type stays open.
    value: Any = None
    claim_key: str = ""
    # Per-entry patch provenance. ``note`` flows to the entity's ChangeSet
    # note; ``cite_specs`` (set only on explicit-field assertions, never the
    # create-owned slug/status scaffolding) is the entry's citation list —
    # every spec is materialized as a CitationInstance on the resulting claim
    # at apply time, so N specs on M claims fan out to M×N support edges
    # through N shared instances.
    note: str = ""
    cite_specs: tuple[CiteSpec, ...] = ()
    # Inline-citation footnotes referenced by ``[[cite:<numeric-handle>]]`` markers
    # in a markdown field's value, keyed by the patch-local numeric handle. Each
    # is a *new* citation minted at apply time (a floating CitationInstance
    # carrying the spec's locator/quote, reached only by its marker), after which
    # the handle markers are rewritten to the minted slug. Existing-slug markers
    # (``[[cite:<slug>]]``) carry nothing here — they self-resolve through
    # standard conversion. Empty for non-cited fields.
    inline_cites: dict[CiteHandle, CiteSpec] = field(default_factory=dict)
    # The file-order index of the authoring patch entry, so ``_persist`` can mint
    # one ChangeSet per entry. The front end stamps it in a second pass (see
    # ``planning.build_plan``), so it is ``None`` only transiently between
    # construction and stamping — always set by apply time.
    entry_index: EntryIndex | None = None
    content_type_id: int | None = None
    object_id: int | None = None
    handle: Handle | None = None
    license_id: LicenseId | None = None
    # Deferred relationship claim identity:
    relationship_namespace: Namespace = ""
    # identity values mix PKs (int) and tag values (str/bool) per the
    # relationship's claim-key schema; truly heterogeneous.
    identity: dict[ClaimValueKey, Any] = field(default_factory=dict)
    # value-key → the handle of the planned entity whose PK fills that identity slot.
    identity_refs: dict[ClaimValueKey, Handle] = field(default_factory=dict)
    # Deferred direct-FK claim value: the handle of the planned entity whose PK
    # becomes this claim's ``value`` (FK claim values store target PKs). Set only
    # when a direct FK field references a same-patch create; the apply layer
    # fills ``value`` after the bulk-create, like ``identity_refs`` does for
    # relationship identity slots.
    value_ref: Handle | None = None


@dataclass
class PlannedClaimRetract:
    """An explicit retraction of a previously-active claim."""

    content_type_id: int
    object_id: int
    claim_key: str
    # Per-entry patch note → the entry's ChangeSet note. A retraction has no
    # new claim, so it carries no ``cite_specs``.
    note: str = ""
    # The file-order index of the authoring patch entry (see
    # ``PlannedClaimAssert.entry_index``); stamped in the same second pass.
    entry_index: EntryIndex | None = None


@dataclass
class IngestPlan:
    """Declarative description of everything a source wants to write."""

    source: Source
    input_fingerprint: str
    # The NNNN-slug data patch filename stem — the applied-ledger key. Required.
    patch_id: str
    entities: list[PlannedEntityCreate] = field(default_factory=list)
    assertions: list[PlannedClaimAssert] = field(default_factory=list)
    retractions: list[PlannedClaimRetract] = field(default_factory=list)
    records_parsed: int = 0
    records_matched: int = 0
    changed_relationship_fields: ChangedRelationshipFields = field(default_factory=dict)
    # Side writes run first inside the apply transaction (before any entity
    # create), each handed the RunReport. Patch-only: citation source upserts.
    pre_write_hooks: list[PreWriteHook] = field(default_factory=list)
    # Read-only previews run only on the dry-run path, each handed the RunReport
    # to append warnings. The dry-run analogue of pre_write_hooks: they surface a
    # committed-state conflict the live hook would warn on at apply (citation
    # source host collisions), without the live path's writes.
    dry_run_preview_hooks: list[DryRunPreviewHook] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # The patch's description, copied to ``IngestRun.note``.
    note: str = ""


@dataclass
class RunReport:
    """Counts and diagnostics returned by ``apply_plan``."""

    records_created: int = 0
    asserted: int = 0
    unchanged: int = 0
    superseded: int = 0
    retracted: int = 0
    rejected: int = 0
    # Citation-source side writes from a patch's ``sources:`` block (pre-write
    # hook). Tracked apart from ``records_created`` (catalog entities) so a
    # sources-only or link-only patch isn't audited as having done nothing.
    sources_created: int = 0
    sources_skipped: int = 0
    source_links_created: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
