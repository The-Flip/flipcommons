"""Guard: product authorization goes through Activity rules, not raw flags.

The project rule (CLAUDE.md, docs/Authz.md): to decide whether a user may
perform a *product action*, gate on an ``Activity`` (``@requires`` /
``gated_inline`` / the registered predicates), never on a raw ``user.is_staff``
/ ``user.is_superuser`` / ``user.email_verified`` read. Raw reads re-spell
policy inline, drift from the registry and are invisible to the capability map
the SPA consumes.

import-linter cannot catch this — it is symbol-level, not import-level: every
API module legitimately imports ``accounts.models`` for the ``User`` type, so a
forbidden-import contract would be all false positives. So this is a source-scan
guard (see ``_source_guard``), the same shape as ``test_liveness_canonical`` and
``test_ranking_is_canonical``: it is the usage counterpart to the import
contracts in pyproject.toml.

Needles are anchored to the ``.attr`` read so they catch attribute access, not
the predicate *names* that pepper the authz registry (``register(..., is_staff)``)
or string keys (``setdefault("is_staff", ...)``).

Exemptions (each is infrastructure or login bootstrap, never a product gate):

- ``core/authz/predicates.py`` — the canonical predicates; they *are* the one
  place the raw flags are read, wrapping them as policy primitives.
- ``core/admin_site.py`` — Django's own ``/djadmin/`` entry gate (framework
  routing, not a catalog/product action).
- ``accounts/management/commands/grant_admin.py`` — operator bootstrap CLI that
  sets the flags in the first place.
- ``accounts/api/workos_match.py`` — WorkOS login/link bootstrap: refuses to
  auto-link privileged rows and mirrors ``email_verified`` from the IdP.
- ``accounts/pending.py`` — the WorkOS pending-signup protocol/read used during
  that bootstrap.
- ``accounts/apps.py`` — patches ``AnonymousUser.email_verified`` so anonymous
  requests are structurally comparable to authenticated ones.
"""

from __future__ import annotations

import pytest

from apps.core.tests._source_guard import offenders

_ALLOW = {
    "core/authz/predicates.py",
    "core/admin_site.py",
    "accounts/management/commands/grant_admin.py",
    "accounts/api/workos_match.py",
    "accounts/pending.py",
    "accounts/apps.py",
}


@pytest.mark.parametrize("needle", [".is_staff", ".is_superuser", ".email_verified"])
def test_product_gates_do_not_read_raw_role_flags(needle: str) -> None:
    found = offenders(needle, allow=_ALLOW)
    assert not found, (
        f"Raw role-flag read ({needle!r}) outside the authz layer in {found}. "
        "Gate product actions on an Activity (@requires / gated_inline / a "
        "registered predicate), not user.is_staff/is_superuser/email_verified. "
        "See docs/Authz.md. If this is genuine auth/admin infrastructure, add the "
        "file to _ALLOW with a one-line reason."
    )
