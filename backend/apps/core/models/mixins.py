"""Abstract base mixins shared across all apps."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import ClassVar, Self, TypeVar, cast

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.expressions import Combinable
from django.db.models.functions import Now
from django.utils.text import slugify

from apps.core.markdown import MarkdownField


class TimeStampedModel(models.Model):
    """Abstract base adding created_at / updated_at timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class LastUpdatedModel(models.Model):
    """Entity freshness — when did this entity last meaningfully change.

    The single definition of "last modified", consumed by both the sitemap's
    ``<lastmod>`` and JSON-LD's ``dateModified`` so the two can never disagree.
    Two facets of the same concept:

    - ``lastmod_expression()`` — a queryset expression, for bulk contexts that
      annotate many rows at once (``SitemappedModel.sitemap_queryset()``, the
      detail-page annotation in ``register_entity_detail_page``).
    - ``last_modified`` — the per-instance value, read off the ``_last_modified``
      annotation those contexts set.

    The default implementation assumes a physical ``updated_at`` column — i.e.
    a concrete subclass also inherits ``TimeStampedModel``. A future *virtual*
    entity (no physical ``updated_at``) inherits this concern standalone and
    overrides both hooks to supply freshness another way. ``Title`` overrides
    only ``lastmod_expression()`` to widen freshness over its child Models.
    """

    class Meta:
        abstract = True

    @classmethod
    def lastmod_expression(cls) -> Combinable:
        """Queryset expression yielding the freshness value. Override to widen.

        ``updated_at`` comes from ``TimeStampedModel`` on the concrete subclass;
        the parity test pins that inheritance contract.
        """
        return models.F("updated_at")

    @property
    def last_modified(self) -> datetime:
        """Per-instance freshness — the value the sitemap emits as ``<lastmod>``.

        Reads the ``_last_modified`` annotation when present — the sitemap and
        the detail-page registrar set it via ``lastmod_expression()`` — else
        falls back to ``updated_at``. For a model that doesn't override
        ``lastmod_expression()`` the fallback is exactly the annotated value.
        For one that does (``Title``), the fallback is the un-widened
        ``updated_at``; that's why every read path the freshness value feeds
        (sitemap, JSON-LD ``dateModified``) annotates rather than relying on
        the property's bare attribute. ``_last_modified`` is a queryset
        annotation, not a declared field, so ``getattr`` with a default is the
        right read.
        """
        annotated = getattr(self, "_last_modified", None)
        if annotated is not None:
            return cast("datetime", annotated)
        return cast("datetime", self.updated_at)  # type: ignore[attr-defined]


class SluggedModel(models.Model):
    """Abstract base for catalog entities that have a unique, non-empty slug.

    Provides the slug field. Models needing max_length > 200 redeclare it.
    Each concrete subclass must add the CHECK constraint to its own Meta
    because Django does not inherit abstract parent constraints when a
    concrete model defines its own ``class Meta``::

        class Meta:
            constraints = [slug_not_blank(), slug_lowercase()]

    Use ``slug_not_blank()`` and ``slug_lowercase()`` to generate the
    constraints — system-wide rule is lowercase-only slugs.
    """

    slug = models.SlugField(max_length=200, unique=True)

    class Meta:
        abstract = True


def unique_slug(obj: models.Model, source: str, fallback: str = "item") -> str:
    """Generate a unique slug with counter disambiguation.

    Appends a counter suffix (-2, -3, …) until the slug is unique within
    the model's table.
    """
    base = slugify(source) or fallback
    slug = base
    counter = 2
    manager = type(obj)._default_manager
    while manager.filter(slug=slug).exclude(pk=obj.pk).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


# ---------------------------------------------------------------------------
# Entity status (claim-controlled lifecycle)
# ---------------------------------------------------------------------------


class EntityStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DELETED = "deleted", "Deleted"


# The claim-controlled lifecycle field name (``LifecycleStatusModel.status``).
# Named here, beside the model that owns it, so layers that must reason about
# lifecycle claims without a model instance — the ingest apply layer and the
# patch adapter — share one source of truth instead of hardcoding ``"status"``.
LIFECYCLE_STATUS_FIELD = "status"


_LifecycleModel = TypeVar("_LifecycleModel", bound="LifecycleStatusModel")


class LifecycleQuerySet(models.QuerySet[_LifecycleModel]):
    def active(self) -> LifecycleQuerySet[_LifecycleModel]:
        """Return entities considered live in the catalog.

        Includes ``status='active'`` and ``status IS NULL`` for legacy ingest
        commands that do not emit status claims yet. Tighten to
        ``status='active'`` only after every ingest path creates status claims.
        """
        return self.filter(
            models.Q(status=EntityStatus.ACTIVE) | models.Q(status__isnull=True)
        )


LifecycleManager = models.Manager.from_queryset(LifecycleQuerySet)


def active_status_q(relation: str) -> models.Q:
    """``Q`` filter for active-status entities reached through *relation*.

    Use inside ``Count(filter=...)`` and similar annotations where the
    queryset ``.active()`` method is not available::

        Count("machine_models", filter=Q(...) & active_status_q("machine_models"))

    Null-inclusive for legacy ingest compatibility — tighten alongside
    ``LifecycleQuerySet.active()`` once every ingest path creates status claims.
    """
    return models.Q(**{f"{relation}__status": EntityStatus.ACTIVE}) | models.Q(
        **{f"{relation}__status__isnull": True}
    )


class LifecycleStatusModel(models.Model):
    """Abstract base adding claim-controlled entity lifecycle status.

    Add to all independent catalog entity models (not aliases, through
    models, or abbreviations).  Each concrete subclass must also add
    ``status_valid()`` to its ``Meta.constraints``.

    Today the only states are ``active`` and ``deleted`` (soft delete).
    Future lifecycle states (e.g. ``draft``, ``archived``) belong on the
    existing ``status`` field, not a parallel field — this class is the
    designated home for entity lifecycle.
    """

    status = models.CharField(
        max_length=10,
        choices=EntityStatus.choices,
        null=True,
        blank=True,
    )

    # ``ClassVar[LifecycleManager[Self]]`` gets us both halves: the custom
    # manager type (so ``.active()`` is visible) and per-subclass model
    # binding (so ``Manufacturer.objects`` types as
    # ``LifecycleManager[Manufacturer]``, not ``LifecycleManager[LifecycleStatusModel]``).
    # Without ``Self``, django-types' default descriptor strips the custom
    # manager class. ``CatalogModel`` redeclares this so ``Self`` rebinds at
    # the catalog level — mypy walks the TypeVar bound, not the concrete class,
    # so without the redeclaration ``model_cls.objects.active()`` (where
    # ``model_cls: type[ModelT: CatalogModel]``) types as
    # ``LifecycleManager[LifecycleStatusModel]``.
    # pyright: ignore on the annotation — ``LifecycleManager`` is the result of
    # ``models.Manager.from_queryset(...)``, which Pylance sees as a variable
    # assignment rather than a class declaration (``reportInvalidTypeForm``).
    # mypy + django-stubs accept it; converting to a ``class LifecycleManager(...)``
    # statement either loses the ``[Self]`` subscript or crashes the django-stubs
    # plugin under multiple inheritance, so we keep the assignment form.
    objects: ClassVar[LifecycleManager[Self]] = LifecycleManager()  # pyright: ignore[reportInvalidTypeForm]

    # Soft-delete walker policy — see apps/catalog/api/soft_delete.py and the
    # check_soft_delete_policy system check in apps/core/checks.py. Concrete
    # subclasses override these frozensets when they need to cascade deletion to
    # dependent entities, or to block deletion when an active referrer reaches
    # them through an M2M through-table or self-referential hierarchy (which the
    # FK PROTECT pass cannot see). Empty defaults keep the walker generic. These
    # live here, with the lifecycle capability, rather than on any one
    # consuming app's base model.
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset()
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset()

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# DescribedModel
# ---------------------------------------------------------------------------


class DescribedModel(models.Model):
    """Adds a long-form markdown ``description`` field.

    Inherit on any model that needs a description.
    """

    description = MarkdownField(blank=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Identity + label foundation
# ---------------------------------------------------------------------------


class IdentifiableModel(models.Model):
    """Abstract base for an entity with a canonical URL-identity value (``public_id``).

    Subclasses may override:
    - public_id_field: str — name of the field carrying URL identity. Defaults
      to ``"slug"``. Multi-segment models materialize the path into a
      ``unique=True`` field and point this at it (Location: ``"location_path"``).
    - public_id_form_field: str — name of the form input from which
      ``public_id_field`` is derived at create time. Defaults to
      ``public_id_field`` itself (the form input is the public id directly,
      as for every shipped model that uses ``"slug"``). Override on models
      whose public id is server-derived from another input — Location's
      ``location_path`` is built from the user's ``slug`` input plus the
      parent's path. Used by collision pre-checks to surface the error
      keyed under the form field the user can actually fix.

    Identity is the foundation under both linking (``LinkableModel``) and
    autocomplete (``AutocompletableModel``); both reach it via
    ``LabeledIdentityModel``.
    """

    public_id_field: ClassVar[str] = "slug"
    # Empty default means "use ``public_id_field`` itself". Resolve with
    # ``cls.public_id_form_field or cls.public_id_field`` at the call site.
    public_id_form_field: ClassVar[str] = ""

    class Meta:
        abstract = True

    @property
    def public_id(self) -> str:
        """Return this entity's URL-identity value (``self.<public_id_field>``)."""
        value: str = getattr(self, self.public_id_field)
        return value

    @classmethod
    def compose_public_id(cls, authored_fields: Mapping[str, object]) -> str:
        """Compose this entity's ``public_id`` from a create's authored claim fields.

        The patch create path uses this to verify that an entity reference
        (e.g. ``location.usa/tx/paris``) agrees with the claims the author
        wrote, so a reference that disagrees with its inputs fails loudly
        instead of creating an internally inconsistent row.

        Most entities' public id *is* the form field, so the default returns
        ``authored_fields[public_id_form_field]``. Entities whose public id is
        server-derived (Location: ``location_path`` from parent + slug)
        override.
        """
        form_field = cls.public_id_form_field or cls.public_id_field
        return str(authored_fields[form_field])


class LabeledModel(models.Model):
    """Abstract base for an entity with a human-readable display ``label``.

    ``label_field`` names the field the label reads (default ``"name"``). The
    ``name`` field itself is declared per-concrete-subclass (different
    max_length / validators per entity), so it cannot be hoisted here.
    """

    label_field: ClassVar[str] = "name"
    # ``name`` is declared per-concrete-subclass (different max_length /
    # validators per entity); the instance-level annotation lets
    # ``type[CatalogModel]`` introspection code read ``.name`` without
    # casting. Django field registration still happens on the concrete
    # subclasses (where ``= models.CharField(...)`` lives), so ``_meta`` is
    # unaffected — but django-stubs's plugin can't see a field here at the
    # abstract level, so ``_meta.get_field("name")`` on ``type[CatalogModel]``
    # needs ``# type: ignore[misc]`` at the one site that calls it.
    name: str

    class Meta:
        abstract = True

    @property
    def label(self) -> str:
        """Return this entity's display label (``self.<label_field>``)."""
        value: str = getattr(self, self.label_field)
        return value


class LabeledIdentityModel(IdentifiableModel, LabeledModel):
    """Identity (``public_id``) + display ``label`` — the shared foundation.

    Supplies the ``{value: public_id, label}`` shape an autocomplete row needs
    and is the base under both ``LinkableModel`` (linking) and
    ``AutocompletableModel`` (dropdowns).
    """

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# LinkableModel (link target registration)
# ---------------------------------------------------------------------------


class LinkableModel(LabeledIdentityModel):
    """Abstract base marking a model as a publicly addressable entity with a canonical identifier.

    Subclasses must define:
    - name: CharField
    - entity_type: str — hyphenated canonical public identifier (e.g. 'corporate-entity')
    - entity_type_plural: str — hyphenated canonical plural form (e.g. 'corporate-entities')

    Identity (``public_id`` / ``public_id_field`` / ``public_id_form_field``)
    comes from ``IdentifiableModel``; the display ``label`` (over ``name``)
    from ``LabeledModel`` — both via ``LabeledIdentityModel``.

    ``entity_type`` and ``entity_type_plural`` together are the linguistic
    identity of a kind of entity — the single source of truth consumed by
    ``get_linkable_model`` and ``export_entity_meta``. All URL shapes and
    UI labels derive from them; they do not drive backend behavior beyond
    URL and UI consistency.

    Subclasses that should appear in the wikilink autocomplete picker
    additionally inherit ``apps.core.wikilinks.WikilinkableModel``, which
    carries the picker-presentation contract (label, sort order, autocomplete
    config).

    ``link_url_pattern`` is derived from ``entity_type_plural`` at subclass
    creation time — do not declare it by hand.
    """

    entity_type: ClassVar[str]  # required on concrete subclasses
    entity_type_plural: ClassVar[str]  # required on concrete subclasses
    link_url_pattern: ClassVar[str]

    class Meta:
        abstract = True

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # __init_subclass__ fires before Django's ModelBase sets up ``_meta``,
        # so abstract/concrete cannot be determined via ``_meta.abstract`` here.
        # Instead, treat ``entity_type`` declaration as the concrete-class
        # marker: abstract intermediates (e.g. ``CatalogModel``) must NOT declare
        # ``entity_type``; any subclass that does is treated as concrete and
        # must also declare ``entity_type_plural``. If a future abstract
        # intermediate needs ``entity_type`` set for some reason, this hook's
        # invariant will need revisiting.
        if "entity_type" not in cls.__dict__:
            # Abstract intermediate; nothing to validate or derive.
            return
        entity_type = cls.__dict__["entity_type"]
        if not isinstance(entity_type, str) or not entity_type:
            raise ImproperlyConfigured(
                f"{cls.__name__} inherits LinkableModel but declares "
                f"entity_type as something other than a non-empty string."
            )
        entity_type_plural = cls.__dict__.get("entity_type_plural")
        if not isinstance(entity_type_plural, str) or not entity_type_plural:
            raise ImproperlyConfigured(
                f"{cls.__name__} inherits LinkableModel but does not declare "
                f"entity_type_plural as a non-empty string."
            )
        # Derive link_url_pattern from entity_type_plural. This hook fires
        # once at class creation, so entity_type_plural must be a class-body
        # literal; post-hoc assignment will not re-derive link_url_pattern.
        # ``{public_id}`` resolves at format time to whichever field
        # ``public_id_field`` names — ``slug`` for most models,
        # ``location_path`` for Location, etc.
        cls.link_url_pattern = f"/{entity_type_plural}/{{public_id}}"
        # Collision detection and ``public_id_field`` resolution happen in
        # the system check (apps.core.checks), not here, to avoid depending
        # on Django's _meta being fully wired at __init_subclass__ time.

    def get_absolute_url(self) -> str:
        """Format ``link_url_pattern`` with this entity's ``public_id``."""
        return self.link_url_pattern.format(public_id=self.public_id)


# ---------------------------------------------------------------------------
# SitemappedModel (sitemap membership)
# ---------------------------------------------------------------------------


class SitemappedModel(LinkableModel, LastUpdatedModel):
    """Abstract base marking a model as a member of the sitemap.

    Composes the two prerequisites for a sitemap entry: a canonical URL
    (``LinkableModel``) and a freshness value (``LastUpdatedModel``). The
    sitemap walk (``apps.core.sitemap.all_sitemap_feeds``) keys off this class,
    so a ``LinkableModel`` that is *not* a ``SitemappedModel`` (a future
    linkable-but-virtual entity, say) is simply absent from the sitemap rather
    than crashing on a missing ``sitemap_queryset()``.

    Defaults assume the concrete subclass also inherits ``LifecycleStatusModel``
    (for ``.active()``) and ``TimeStampedModel`` (for ``updated_at``, via the
    ``LastUpdatedModel`` default). Every shipped concrete ``SitemappedModel``
    does, via ``CatalogModel`` + ``TimeStampedModel``. The parity test in
    ``apps/core/tests/test_sitemapped_model_lifecycle_parity.py`` pins that
    contract so a future subclass without the mixins fails CI rather than
    crashing at sitemap render. A subclass that doesn't / can't satisfy the
    contract MUST override ``sitemap_queryset`` (return ``cls.objects.none()``
    to opt out, or build the queryset by hand).
    """

    class Meta:
        abstract = True

    @classmethod
    def sitemap_queryset(cls) -> models.QuerySet[Self]:
        """Active rows to include in the sitemap, annotated with ``_last_modified``.

        Default: ``.active()`` rows with ``_last_modified`` from
        ``lastmod_expression()`` (``updated_at`` unless a subclass widens it).
        Override ``lastmod_expression()`` to widen ``lastmod`` (e.g. aggregate
        child timestamps); override this method only to narrow membership, or
        return ``cls.objects.none()`` to opt out of the sitemap entirely. Use
        ``non_canonical_detail_slugs()`` to drop a detail URL for canonical-URL
        reasons without removing the row.
        """
        # ``LinkableModel`` itself doesn't carry ``status`` or the lifecycle
        # manager; the default depends on the parity-tested mixin contract
        # above, so cast at the boundary rather than tightening this abstract
        # base's bases (which would force every ``SitemappedModel`` to be a
        # ``LifecycleStatusModel`` — too tight for future non-lifecycle
        # entities that opt out via override).
        objects = cast("LifecycleManager[Self]", cls._default_manager)
        return cast(
            "models.QuerySet[Self]",
            objects.active()
            .annotate(_last_modified=cls.lastmod_expression())
            # ``updated_at`` comes from ``TimeStampedModel``; django-stubs
            # can't see fields from a sibling mixin on the abstract base.
            # Parity test pins the contract.
            .only(cls.public_id_field, "updated_at")  # type: ignore[misc]
            .order_by(cls.public_id_field),
        )

    @classmethod
    def non_canonical_detail_slugs(cls) -> Iterable[str]:
        """Slugs whose ``catalog-detail`` URL is non-canonical.

        Default: empty. Override when the detail page collapses to a
        different entity's page in the UI (canonical URL lives elsewhere) —
        the row stays in ``sitemap_queryset()`` so ``/edit-history`` and
        ``/sources`` still emit, but its detail URL is omitted from the
        sitemap.

        Returned slugs must already be members of ``sitemap_queryset()``;
        slugs outside that set are ignored (defensive — they wouldn't appear
        anyway).
        """
        return ()
