"""The :class:`PatchEntityRegistry`: the front end's single registry of what
entity a reference names — a committed entity (:meth:`lookup_existing`), a
same-patch create (:meth:`created_handle`), or neither (the caller's "no such
record" case).

This is the patch compiler's *symbol table*: it binds each reference
(``entity_type.public_id``) to the entity it denotes, so a *later* entry can
refer to an entity an *earlier* entry creates. It reads live committed state and
applies no post-patch resolution — it resolves *references to entities*, never
*claims to values*. That boundary is the point of the type: keep it a name→entity
binding, and do not grow claim resolution onto it.
"""

from __future__ import annotations

from django.db import models

from apps.catalog.ingestion.patches._types import _CreatedKey
from apps.catalog.ingestion.plan import Handle
from apps.catalog.models import CatalogModel


class PatchEntityRegistry:
    """The symbol table the front end resolves references against.

    A committed entity and a same-patch create are keyed the same way — model +
    public_id — but never collide: the entity lives in the database, the create
    in memory, and a reference tries the database (:meth:`lookup_existing`) then
    the in-memory registry (:meth:`created_handle`).
    """

    def __init__(self) -> None:
        # Same-patch creates: concrete model class + public_id -> handle, so a
        # *later* entry can reference an entity an *earlier* entry creates. A
        # miss falls through to the committed lookup; only neither-found errors.
        self._created: dict[_CreatedKey, Handle] = {}
        # Create entry-refs already recorded this patch. Dedups by the entry-ref
        # label (a different key from ``_created``'s concrete-class + public_id):
        # a second create for one ref would mint a duplicate handle and blow up
        # deep in the apply layer, so it is rejected cleanly up front.
        self._created_refs: set[str] = set()

    def lookup_existing(
        self, model_class: type[CatalogModel], public_id: str
    ) -> CatalogModel | None:
        """The committed entity for ``(model_class, public_id)``, or ``None``."""
        return model_class._default_manager.filter(
            **{model_class.public_id_field: public_id}
        ).first()

    def created_handle(
        self, model_class: type[models.Model], public_id: str
    ) -> Handle | None:
        """The handle of a same-patch create for ``(model_class, public_id)``.

        ``model_class`` is keyed as the *resolved concrete class* — for an FK or
        relationship member, the target's ``related_model`` (typed by Django as
        ``Model``), matching ``_CreatedKey``'s identity (see its docstring).
        """
        return self._created.get(_CreatedKey(model_class, public_id))

    def has_create_ref(self, ref: str) -> bool:
        """Whether a create entry with this ref was already recorded."""
        return ref in self._created_refs

    def mark_create_ref(self, ref: str) -> None:
        """Record a create entry-ref, before emitting, to reject a duplicate."""
        self._created_refs.add(ref)

    def register_create(
        self, model_class: type[CatalogModel], public_id: str, *, handle: Handle
    ) -> None:
        """Register a same-patch create's handle for backward references.

        Called *after* the create is emitted, so the create's own FK fields
        (resolved against earlier creates inside ``_add_create``) cannot resolve
        the entity onto itself.
        """
        self._created[_CreatedKey(model_class, public_id)] = handle
