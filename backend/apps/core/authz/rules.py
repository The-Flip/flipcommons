"""Rules owned by the core app itself.

Per-app rule files normally live at `apps/<app>/authz.py`. Core uses
`apps/core/authz/` as the engine package, so its rule registrations
live in this submodule instead and are imported by `core/apps.py:
ready()`.

Today this covers user-state and tooling-surface activities — the
rate limiter's exemption check, and the Django-admin nav-link gate
the SPA reads from `/me/`. Both describe an attribute (or which
tool a user may reach) rather than a CRUD route, so they don't
correspond to a single domain app's models.

The policy is the security boundary; what it permits should be
stated explicitly, not inferred from whatever upstream gate happens
to fire first. Every rule states all of its requirements, even when
some are redundant on today's call paths — the next caller might
take a different path. ``RATE_LIMIT_EXEMPT`` requires email
verification because rate-limit exemption is a privilege we only
grant to verified staff; ``DJANGO_ADMIN_ACCESS`` does not (today)
because Django itself only gates ``/djadmin/`` on ``is_staff`` and the
SPA nav link mirrors what's actually reachable.

Predicate conventions for rules in this module:

- **Always include ``is_authenticated``.** Even when another
  predicate (e.g. ``is_staff``) would already deny anonymous on the
  verdict, the *denial code* matters. ``AUTH_REQUIRED`` is the
  highest-priority code and is what the SPA wants to show a logged-
  out user; without ``is_authenticated`` the only failing predicate
  would be ``is_staff`` and anonymous would surface
  ``ROLE_REQUIRED`` — wrong UX copy and mis-categorized in the
  audit log.

- **Default to including ``email_verified``.** Activities that
  legitimately should not require verification must add themselves
  to ``_ACTIVITIES_EXEMPT_FROM_EMAIL_VERIFIED`` in
  ``test_authz_registry_complete.py`` with a comment explaining why.
"""

from __future__ import annotations

from .predicates import email_verified, is_authenticated, is_staff
from .registry import register
from .types import Activity

register(Activity.RATE_LIMIT_EXEMPT, is_authenticated, email_verified, is_staff)
register(Activity.DJANGO_ADMIN_ACCESS, is_authenticated, is_staff)
register(Activity.OBSERVABILITY_DEBUG, is_authenticated, email_verified, is_staff)
register(Activity.VIEW_ADMIN_AREA, is_authenticated, email_verified, is_staff)
