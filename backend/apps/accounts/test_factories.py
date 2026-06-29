"""Test-only factories for accounts models.

Kept outside ``tests/`` so test helpers can be imported across apps
without circular dependencies or duplicated conftest fixtures.

Always prefer ``make_user`` over ``User.objects.create_user`` in tests
so every site picks up future ``User`` field defaults (e.g.
``email_verified``) without per-call overrides. Pass ``email=...`` when
the literal value is what the test asserts on.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from .models import User

if TYPE_CHECKING:
    from apps.actors.models import Actor

_DEFAULT_ATTRIBUTOR = "test-attributor"  # <= 20 chars (username limit)


def make_user(
    *,
    email: str | None = None,
    username: str | None = None,
    **overrides: Any,  # noqa: ANN401 - matches UserManager.create_user signature.
) -> User:
    """Create a ``User`` for tests with sensible defaults.

    Default email and username are unique per call (UUID suffix), so
    ``make_user()`` is safe to call twice without collision. Tests that
    care about a specific value pass it explicitly.
    """
    if email is None:
        email = f"editor-{uuid.uuid4().hex[:8]}@example.com"
    if username is None:
        username = f"editor-{uuid.uuid4().hex[:8]}"
    overrides.setdefault("email_verified", True)
    return User.objects.create_user(email=email, username=username, **overrides)


def default_actor() -> Actor:
    """A shared default attribution ``Actor`` for tests needing an attributor.

    Backed by one get-or-created default ``User`` — editorial attribution is
    normally a person, and ``User`` is the actor backing the citation factories
    can reach (``apps.provenance.Source`` sits a tier above them). Reused so
    default test attribution funnels through one actor; tests asserting on real
    attribution pass their own ``created_by`` instead.
    """
    user = User.objects.filter(username=_DEFAULT_ATTRIBUTOR).first()
    if user is None:
        user = make_user(
            username=_DEFAULT_ATTRIBUTOR, email=f"{_DEFAULT_ATTRIBUTOR}@example.com"
        )
    return user.actor
