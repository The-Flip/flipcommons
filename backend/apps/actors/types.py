"""Named scalar types owned by the actors app.

Transparent aliases (``type X = …``) — they document intent at signature sites
without changing interop with the bare ``int`` the Django ORM returns.
"""

from __future__ import annotations

type ActorId = int
"""The primary key of an Actor — who an assertion or change is attributed to."""

type ActorResolutionPriority = int
"""An actor's precedence when its claims compete for a field. Higher wins. """
