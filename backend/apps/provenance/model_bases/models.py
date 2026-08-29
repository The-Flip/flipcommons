"""Abstract bases for claim-controlled entities and addressable claim subjects.

The citation-agnostic substrate every claim-controlled model inherits — catalog
and media today, citation eventually. Kept a dependency-free leaf on purpose: it
imports only ``apps.core`` (and names ``provenance.Claim`` solely through the
string label of a ``GenericRelation``). Two import-linter contracts pin that:
the ``Provenance app internal stack`` layer keeps it from reaching up into the
provenance *domain* (``Claim``, ``ChangeSet``, ``Source``), and the
``Claim-control bases stay a core-only leaf`` forbidden contract blocks the
cross-app edges the global tiers would otherwise permit (provenance sits above
citation/accounts). When a lower-tier app needs to inherit these bases, this
package lifts out to a top-level app via ``git mv`` — still migration-free,
because every base is abstract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from apps.core.models import LifecycleStatusModel, LinkableModel

if TYPE_CHECKING:
    from .claim_relationships import ClaimRelationshipSpec

__all__ = [
    "ClaimControlledModel",
    "ClaimThroughModel",
    "LinkableClaimModel",
    "LinkableLifecycleClaimModel",
]


class ClaimControlledModel(models.Model):
    """Abstract base for entities with claim-controlled fields.

    Declares the reverse-accessor to provenance claims and the typed ``slug``
    / ``name`` shape that claim-resolver helpers read generically.  Does NOT
    imply URL-addressability, globally-unique slugs, or status tracking —
    those are ``LinkableModel`` / ``SluggedModel`` / ``LifecycleStatusModel``
    concerns and are layered in independently at the concrete class.

    **Diamond-inheritance constraint — do not weaken without refactoring.**
    Concrete catalog models combine ``CatalogModel`` and ``MediaSupportedModel``,
    both of which extend ``ClaimControlledModel``, so this class is reached
    via two abstract paths.  The diamond is safe today only because every
    name-bearing thing here is either a ``GenericRelation`` (routed into
    ``_meta.private_fields`` by ``contribute_to_class(..., private_only=True)``
    and skipped by Django's clash check) or a bare type annotation (no
    Django field, no ``_meta`` registration).  Adding any non-private field
    here — anything that lands in ``_meta.local_fields`` or
    ``_meta.local_many_to_many``, e.g. a regular ``CharField`` or ``FK`` —
    would trigger ``FieldError("clashes with field of the same name")`` at
    concrete-model construction.  If you need to add such a field, refactor
    the diamond first (e.g. lift the field higher, or break the inheritance).
    """

    # Instance-level annotations let ``type[ClaimControlledModel]`` code read
    # ``.slug`` / ``.name`` without casting.  Concrete subclasses declare the
    # actual CharField / SlugField with their own max_length and validators.
    slug: str
    name: str

    # Field names excluded from claim control on this model.
    # Default empty so most models are unaffected.
    # Subclasses override with their own ``frozenset``.
    claims_exempt: ClassVar[frozenset[str]] = frozenset()

    # Joins needed by ``claim_display_label()`` when this model is referenced
    # from an FK-bearing claim value. The display engine applies them to its
    # one batched query per target model, so an override remains N+1-safe.
    claim_display_select_related: ClassVar[tuple[str, ...]] = ()

    # Self-FK columns whose graph must stay flat: one hop only, so a row with
    # the FK set may not itself be pointed at, and its target may not have the
    # FK set. The rule is cross-row (no CHECK constraint can express it), so
    # the claim resolvers enforce it over active rows at write time. Default
    # empty so most models pay nothing; requires a lifecycle status column,
    # because "flat" is judged among live rows only.
    flat_self_fks: ClassVar[frozenset[str]] = frozenset()

    claims = GenericRelation("provenance.Claim")

    class Meta:
        abstract = True

    def claim_display_label(self) -> str:
        """Label used when this row is referenced from a displayed claim value.

        Models may override this together with ``claim_display_select_related``
        when their concise provenance label needs related data. The generic
        default preserves the historical ``str(instance)`` behavior.
        """
        return str(self)


class ClaimThroughModel(models.Model):
    """Discovery marker for claim-controlled relationship through-models.

    Defines the universe of materialized relationship tables a
    :class:`~.claim_relationships.ClaimRelationshipSpec` drives, so the
    spec-walk can find every one and a through-model missing its spec fails the
    startup validator loudly rather than being silently skipped. Discovery only:
    no abstract methods, no fields — it adds no table, column or migration. The
    ``claim_relationship_spec`` ClassVar is the per-model declaration; the
    annotation is unevaluated (``from __future__ import annotations``), so the
    reference to :class:`ClaimRelationshipSpec` stays type-checking-only and the
    leaf imports nothing from :mod:`.claim_relationships` at runtime.
    """

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec]

    class Meta:
        abstract = True


class LinkableClaimModel(LinkableModel, ClaimControlledModel):
    """Abstract contract for an *addressable claim subject*.

    A model can be named in a data patch (or addressed by URL) when it is both
    **linkable** (publicly addressable) and **claim-controlled**.
    ``LinkableClaimModel`` is exactly that conjunction —
    ``LinkableModel`` (core) + ``ClaimControlledModel`` (provenance) — and
    provenance is the one layer that sees both bases. It declares no fields, so
    it adds no table, content-type or migration; it exists only as the target
    contract the addressing-dependent write paths bind.

    The bulk pipeline (``claim_ingest``) binds this to resolve
    ``entity_type:public_id`` references; the domain's URL routing binds it for
    the same reason. The interactive ``execute_*`` write functions bind the
    looser ``ClaimControlledModel`` instead, because their caller has already
    resolved the row and needs nothing about addressing.

    **Required (the bound).** Without these a model cannot be a target at all:

    - *Addressing* (``LinkableModel``): ``entity_type`` + the
      ``get_linkable_model()`` registry for content-type dispatch;
      ``public_id`` to resolve ``entity_type:public_id`` → row; ``name``/label
      for error messages and alias folding.
    - *Claims* (``ClaimControlledModel``): ``get_claim_fields()`` introspection;
      reads and writes only claims.

    No narrower bound works: ``IdentifiableModel`` alone lacks ``entity_type``,
    which the addressing scheme requires. ``MediaSupportedModel`` is
    claim-controlled but not linkable — media enters as a ``media_attachment``
    relationship claim on a linkable entity, not as its own target.

    **Discovered (used when present, never bound).** Reached through a guard or
    introspection so they stay optional — a target lacking them is still
    create/edit-patchable:

    - *Lifecycle* (``LifecycleStatusModel``), via ``has_lifecycle()``: create
      stamps ``status='active'``; ``delete:`` routes through the soft-delete
      planner. A lifecycle-less target → only ``delete:`` rejects it.
    - *Markdown content* (``DescribedModel``), via ``get_markdown_fields()``:
      inline-citation validation in description text.

    Binding either would force the capability onto every target — the
    re-tightening this contract exists to avoid.

    **Ignored (the write paths never touch).** Sitemapping
    (``SitemappedModel``), ``lastmod``/timestamps and any other
    web-presentation capability sit *above* ``LinkableModel`` on the core
    chain, so a path bound here is structurally blind to them. Do not fold them
    in: sitemap membership is a read/presentation concern, irrelevant to
    writing claims.
    """

    class Meta:
        abstract = True


class LinkableLifecycleClaimModel(LifecycleStatusModel, LinkableClaimModel):
    """Abstract contract for an *addressable, soft-deletable claim subject*.

    ``LinkableClaimModel`` + ``LifecycleStatusModel`` — the conjunction the
    surfaces that *write the lifecycle status claim* require as a precondition,
    not a discovered refinement:

    - **soft-delete / restore** — a user "delete" is a ``status=deleted`` claim;
      restore writes ``status=active``. The operation *is* a lifecycle write, so
      ``.status`` / ``.active()`` are hard requirements.
    - **create** — every create stamps the ``status`` column and writes a
      ``status=active`` claim, and filters its collision / parent lookups
      through ``.active()``.

    Binding this base turns what would otherwise be a runtime ``AttributeError``
    (``.active()`` on a plain manager, ``.status`` on a non-lifecycle field)
    into a compile-time error at the registration site. Surfaces that only
    *read* claims and never write lifecycle bind something looser —
    ``LinkableClaimModel`` or less.

    Declares no fields — it only conjoins two abstract bases — so it adds no
    table, content-type or migration. The base order (``LifecycleStatusModel``
    then ``LinkableClaimModel``) lets a model that already lists those two
    leaves in that order re-parent onto this combined base with no change to
    its MRO leaf order.
    """

    class Meta:
        abstract = True
