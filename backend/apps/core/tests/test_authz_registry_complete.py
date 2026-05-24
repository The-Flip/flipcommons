"""Asserts every Activity has a registered rule at startup.

This test deliberately does NOT use the `isolated_registry` fixture.
It reads the real, app-`ready()`-populated registry and would pass
trivially against an empty one.

A new `Activity` enum member with no per-app rule registration is what
this catches: the runtime would `LookupError` instead of returning a
permission decision, which is correct but only useful if someone hits
the route. This test makes that misconfiguration a CI failure.
"""

from __future__ import annotations

import pytest

from apps.core.authz.evaluator import check
from apps.core.authz.predicates import is_authenticated
from apps.core.authz.registry import get_rule
from apps.core.authz.test_factories import StubPolicyUser
from apps.core.authz.types import Activity, DenialCode, Deny


@pytest.mark.parametrize("activity", list(Activity))
def test_every_activity_has_a_registered_rule(activity: Activity) -> None:
    rule = get_rule(activity)
    assert rule is not None, (
        f"Activity {activity!r} has no registered rule. Add a "
        f"`register({activity.name}, ...)` call to the relevant app's "
        f"`authz.py`, and ensure that `apps.py: ready()` imports the "
        f"module."
    )
    assert rule.predicates, (
        f"Activity {activity!r} registered with no predicates — that "
        f"would auto-allow every caller. Register at least "
        f"`is_authenticated, is_active`."
    )


# Activities whose rules deliberately do NOT include the
# `email_verified` predicate. The default for every new activity is
# to require email verification; this set is the documented exception
# list. Each member needs a per-activity comment explaining why
# verification isn't required.
_ACTIVITIES_EXEMPT_FROM_EMAIL_VERIFIED = frozenset(
    {
        # `django_admin.access` exists to drive the SPA's "Django
        # Admin" nav link. Django itself gates `/djadmin/` on `is_staff`
        # only — not email verification — so the SPA link mirrors
        # what's actually reachable. Tightening this activity without
        # also tightening Django's gate would hide the link from
        # users who can still type `/djadmin/` directly.
        Activity.DJANGO_ADMIN_ACCESS,
    }
)


def _target_less_activities() -> list[Activity]:
    """Activities whose rules can be evaluated with ``target=None``.

    A rule that declares a ``target`` Protocol can't be evaluated with
    ``target=None`` — the evaluator raises ``TypeError`` before
    reaching its predicates (see ``check()``'s guard). The
    launch-predicate completeness tests below run
    ``check(user, activity)`` with no target, so activities whose
    rules declare a target Protocol are excluded — their launch
    behavior is exercised in app-specific tests with a concrete
    target stub. Activities with ``target_aware=True`` but no
    ``target`` Protocol (e.g. ``claim.revert``, which reserves the
    wire slot but reads nothing off the target) are still included.
    """
    out: list[Activity] = []
    for a in Activity:
        rule = get_rule(a)
        if rule is None or rule.target is not None:
            continue
        out.append(a)
    return out


@pytest.mark.parametrize(
    "activity",
    [
        a
        for a in _target_less_activities()
        if a not in _ACTIVITIES_EXEMPT_FROM_EMAIL_VERIFIED
    ],
)
def test_every_activity_requires_email_verified(activity: Activity) -> None:
    """An authenticated, active, unverified user must be denied with
    VERIFICATION_REQUIRED on every launch activity.

    A future activity that forgets the `email_verified` predicate would
    auto-allow unverified users — this test pins that invariant. Different
    failure mode than the rule-presence test above, so kept as a separate
    function rather than a parametrize expansion.

    The stub passes the role predicates (`is_staff`, `is_superuser`) so
    activities that gate on a role still surface VERIFICATION_REQUIRED
    rather than ROLE_REQUIRED — the only failing predicate is the one
    this test exists to pin.

    Activities listed in `_ACTIVITIES_EXEMPT_FROM_EMAIL_VERIFIED`
    skip this pin; see that set's comment for the per-activity reason.
    """
    user = StubPolicyUser(
        is_authenticated=True,
        is_active=True,
        is_email_verified=False,
        is_staff=True,
        is_superuser=True,
    )
    decision = check(user, activity)
    assert isinstance(decision, Deny), (
        f"Activity {activity!r} allowed an unverified user — missing "
        f"`email_verified` predicate in the rule registration."
    )
    assert decision.code is DenialCode.VERIFICATION_REQUIRED, (
        f"Activity {activity!r} denied an unverified user with code "
        f"{decision.code!r}, expected VERIFICATION_REQUIRED."
    )


@pytest.mark.parametrize("activity", _target_less_activities())
def test_every_activity_denies_anonymous_with_auth_required(
    activity: Activity,
) -> None:
    """An anonymous caller must be denied with `AUTH_REQUIRED`.

    Two invariants in one assertion:

    1. **Verdict.** `compute_capability_map` claims anonymous callers
       get an all-false map. A future rule that forgets to deny
       anonymous would let logged-out users through, and the SPA
       would render affordances for them.
    2. **Code.** The denial code shapes UX copy and audit-log
       categorization. Anonymous should always surface `AUTH_REQUIRED`
       (highest-priority code, "sign in" message), never `ROLE_REQUIRED`
       or anything else. The convention enforced by this assertion is
       that every rule includes `is_authenticated`, even when another
       predicate would already deny anonymous on the verdict —
       see ``apps/core/authz/rules.py`` for the rationale.

    Tested via `check()` rather than by inspecting `rule.predicates`
    so the invariant survives a refactor that composes predicates
    differently — what matters is the verdict and the code.
    """
    rule = get_rule(activity)
    assert rule is not None  # covered by the rule-presence test above

    # Sanity: `is_authenticated` itself denies anonymous. Caught by
    # the predicate's own unit tests, but cheap to re-pin here so a
    # regression produces an informative failure on this test instead
    # of leaking through to every rule that depends on it.
    anon_stub = StubPolicyUser(is_authenticated=False, is_active=False)
    assert isinstance(is_authenticated(anon_stub, None, None), Deny), (
        "is_authenticated regression: predicate now allows anonymous; "
        "every rule's anonymous-deny invariant is broken."
    )

    decision = check(anon_stub, activity)
    assert isinstance(decision, Deny), (
        f"Activity {activity!r} allowed an anonymous caller. Every "
        f"rule must include `is_authenticated` in its predicate chain."
    )
    assert decision.code is DenialCode.AUTH_REQUIRED, (
        f"Activity {activity!r} denied anonymous with code "
        f"{decision.code!r}, expected AUTH_REQUIRED. The rule is "
        f"missing `is_authenticated` — add it. Even when another "
        f"predicate (e.g. `is_staff`) would already deny on the "
        f"verdict, the code matters for UX copy and audit logs. "
        f"See `apps/core/authz/rules.py` for the convention."
    )
