"""Abstract base mixins shared across all apps."""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, Self, TypeVar, cast

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.functions import Now
from django.utils.text import slugify

from apps.core.markdown import MarkdownField


class TimeStampedModel(models.Model):
    """Abstract base adding created_at / updated_at timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


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
# LinkableModel (link target registration)
# ---------------------------------------------------------------------------


class LinkableModel(models.Model):
    """Abstract base marking a model as a publicly addressable entity with a canonical identifier.

    Subclasses must define:
    - name: CharField
    - entity_type: str — hyphenated canonical public identifier (e.g. 'corporate-entity')
    - entity_type_plural: str — hyphenated canonical plural form (e.g. 'corporate-entities')

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

    ``entity_type`` and ``entity_type_plural`` together are the linguistic
    identity of a kind of entity — the single source of truth consumed by
    ``get_linkable_model`` and ``export_catalog_meta``. All URL shapes and
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
    public_id_field: ClassVar[str] = "slug"
    # Empty default means "use ``public_id_field`` itself". Resolve with
    # ``cls.public_id_form_field or cls.public_id_field`` at the call site.
    public_id_form_field: ClassVar[str] = ""
    # ``name`` is declared per-concrete-subclass (different max_length /
    # validators per entity); the instance-level annotation lets
    # ``type[LinkableModel]`` introspection code read ``.name`` without
    # casting. Django field registration still happens on the concrete
    # subclasses (where ``= models.CharField(...)`` lives), so ``_meta`` is
    # unaffected — but django-stubs's plugin can't see a field here at the
    # abstract level, so ``_meta.get_field("name")`` on ``type[CatalogModel]``
    # needs ``# type: ignore[misc]`` at the one site that calls it.
    name: str
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

    @property
    def public_id(self) -> str:
        """Return this entity's URL-identity value (``self.<public_id_field>``)."""
        value: str = getattr(self, self.public_id_field)
        return value

    # ---------------------------------------------------------------------
    # Sitemap hooks
    # ---------------------------------------------------------------------
    # Defaults assume the concrete subclass also inherits
    # ``LifecycleStatusModel`` (for ``.active()``) and ``TimeStampedModel``
    # (for ``updated_at``). Every shipped concrete ``LinkableModel`` does, via
    # ``CatalogModel`` + ``TimeStampedModel``. The parity test in
    # ``apps/core/tests/test_linkable_model_lifecycle_parity.py`` pins that
    # contract so a future subclass without the mixins fails CI rather than
    # crashing at sitemap render. A subclass that doesn't / can't satisfy the
    # contract MUST override ``sitemap_queryset`` (return ``cls.objects.none()``
    # to opt out, or build the queryset by hand).

    @classmethod
    def sitemap_queryset(cls) -> models.QuerySet[Self]:
        """Active rows to include in the sitemap, annotated with ``_sitemap_lastmod``.

        Default: ``.active()`` rows with ``_sitemap_lastmod = updated_at``.
        Override to widen ``lastmod`` (e.g. aggregate child timestamps) — not
        to narrow membership for canonical-URL reasons; use
        ``non_canonical_detail_slugs()`` for that.

        Return ``cls.objects.none()`` to opt a ``LinkableModel`` out of the
        sitemap entirely.
        """
        # ``LinkableModel`` itself doesn't carry ``status`` or the lifecycle
        # manager; the default depends on the parity-tested mixin contract
        # above, so cast at the boundary rather than tightening the abstract
        # base's bases (which would force every ``LinkableModel`` to be a
        # ``LifecycleStatusModel`` — too tight for future non-lifecycle
        # entities that opt out via override).
        objects = cast("LifecycleManager[Self]", cls._default_manager)
        return cast(
            "models.QuerySet[Self]",
            objects.active()
            .annotate(_sitemap_lastmod=models.F("updated_at"))
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
