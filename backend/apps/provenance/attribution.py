"""Actor → backing-record accessors, shared by every attribution reader.

The schema-free half of the attribution helpers: given a ``Claim`` /
``ChangeSet`` ``Actor``, reach its backing record by type. ``backing_model``
("user" / "source") is both the reverse-one-to-one accessor (``actor.user`` /
``actor.source``) and the type discriminator — the single model-driven routing
point, mirroring how ``claim_writer`` already stamps the legacy column.

Lives below ``schemas`` in the provenance internal stack so ``licensing`` (and
other low layers) can use it; the schema-producing counterpart ``actor_author``
stays in ``helpers`` with the display layer. Callers must ``select_related`` the
relevant backing one-to-one (``actor__source`` / ``actor__user``) so each lookup
is a column read, not a query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.core.exceptions import ObjectDoesNotExist

from apps.actors.models import Actor

if TYPE_CHECKING:
    from apps.accounts.models import User

    from .models import Source


def source_backing(actor: Actor | None) -> Source | None:
    """Return the backing ``Source`` when *actor* is source-backed, else ``None``.

    For licensing and export readers that surface source attribution and treat
    user-backed actors as "no source" — the old ``claim.source is None`` case.
    Accepts ``None`` so callers needn't guard. Returns ``None`` for an orphaned
    actor (backing row deleted) rather than raising.
    """
    if actor is None or actor.backing_model != "source":
        return None
    try:
        return cast("Source", getattr(actor, actor.backing_model))
    except ObjectDoesNotExist:  # orphaned actor — backing row deleted
        return None


def actor_user(actor: Actor | None) -> User | None:
    """Return the backing ``User`` when *actor* is user-backed, else ``None``.

    The user-only counterpart to :func:`source_backing`. ``None`` for
    source-backed actors, and for an orphaned actor (backing row deleted) rather
    than raising.
    """
    if actor is None or actor.backing_model != "user":
        return None
    try:
        return cast("User", getattr(actor, actor.backing_model))
    except ObjectDoesNotExist:  # orphaned actor — backing row deleted
        return None


def actor_user_id(actor: Actor | None) -> int | None:
    """Backing user's pk when *actor* is user-backed, else ``None``.

    The actor-native replacement for reading ``claim.user_id`` /
    ``changeset.user_id`` for display (e.g. the edit-history revert-ownership
    hint) — the old ``user_id is None`` case for source-backed actors.
    """
    user = actor_user(actor)
    return user.pk if user is not None else None
