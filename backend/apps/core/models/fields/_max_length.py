"""Shared length-CHECK helper for the bounded text field classes.

``BoundedTextField`` and ``MarkdownField`` share nothing else; this is the
one piece of machinery both reach for.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models.constraints import CheckConstraint

# The ``length`` transform that makes ``Q(field__length__lte=N)`` resolve
# is registered in :meth:`apps.core.apps.CoreConfig.ready` — Django doesn't
# register it by default, and doing it here would be a module-import side
# effect on Django's global lookup registry.

# Postgres default identifier length. Constraint names longer than this
# are silently truncated by Postgres, which breaks idempotent migrations.
_PG_IDENTIFIER_MAX = 63


def _contribute_max_length_check(
    field: models.Field[Any, Any], cls: type[models.Model], name: str
) -> None:
    """Append a ``char_length(field) <= max_length`` CHECK to ``cls._meta.constraints``.

    Used by :class:`~apps.core.models.fields.text.BoundedTextField` and
    :class:`~apps.core.models.fields.markdown.MarkdownField` to auto-attach
    a length CHECK without each model having to declare one.

    ``__length`` compiles to Postgres ``char_length()`` — characters, not
    bytes — so emoji and combining marks count as one each.
    """
    max_length = field.max_length
    if max_length is None:  # pragma: no cover - guarded at field __init__
        raise ValueError(f"{type(field).__name__} requires max_length")

    constraint_name = f"{cls._meta.app_label}_{cls._meta.model_name}_{name}_max_length"
    # Hard failure (not assert): Python -O strips asserts, which would
    # silently let an over-long name through to Postgres where it would
    # be truncated and break idempotent migrations.
    if len(constraint_name) > _PG_IDENTIFIER_MAX:
        raise ValueError(
            f"Constraint name {constraint_name!r} is {len(constraint_name)} chars; "
            f"Postgres truncates beyond {_PG_IDENTIFIER_MAX}."
        )

    # The ``length`` transform compiles to Postgres ``char_length()`` —
    # characters, not bytes — so emoji and combining marks count as one.
    constraint = CheckConstraint(
        condition=models.Q(**{f"{name}__length__lte": max_length}),
        name=constraint_name,
    )
    cls._meta.constraints = [*cls._meta.constraints, constraint]
