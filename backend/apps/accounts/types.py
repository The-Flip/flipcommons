"""Scalar types for the accounts app.

Dependency-free by design: no Django model imports, so annotation-only callers
can name these without dragging ``User`` and its migration state along. See
docs/Python.md, "Keep a semantic scalar alias in a dependency-free leaf module".
"""

from __future__ import annotations

type Username = str
"""A user's chosen public handle — their URL identity at ``/users/<username>``.

Lowercase alphanumerics joined by single hyphens, 3-20 characters; the format
policy lives in ``usernames.py``. Distinct from ``UserId`` (the primary key)
and from the email, which is the ``USERNAME_FIELD`` Django authenticates on.
"""

type WorkOsUserId = str
"""The id of the WorkOS-side user row a local ``User`` is bound to.

Scoped to a single WorkOS *environment*: the same person has different ids in
the dev and prod environments, so a value read from production is meaningless
against a local sign-in. ``User.workos_user_id`` is nullable — an unbound row
either predates its first sign-in or was unlinked by the soft-delete webhook.
"""
