"""Route-inventory test: every mutating route is gated or explicitly public.

Walks every Ninja router in the project and asserts every mutating
operation carries exactly one of:

    @requires(Activity.X)        — the canonical gate; enforced at request time.
    @gated_inline(Activity.X)    — view body calls policy.check() itself.
    @public_mutation(reason)     — deliberately ungated; reason captured.

A mutating route with no marker (or with two) fails the test. There is
no allowlist file — every exception is the @public_mutation decorator
at the view, where the reason lives next to the route.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable

from apps.core.authz.markers import (
    ACTIVITY_ATTR,
    GATED_INLINE_ATTR,
    PUBLIC_ATTR,
    get_gated_inline_activity,
    get_required_activity,
)
from apps.core.authz.route_walker import iter_operations
from apps.core.authz.types import Activity
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    DELETE_RATE_LIMIT_SPEC,
    EDIT_RATE_LIMIT_SPEC,
    RateLimitSpec,
    get_rate_limit_exempt_reason,
    get_rate_limit_spec,
)
from config.api import api

# `op.methods` from Ninja is uppercase. Do NOT reuse the lowercase
# MUTATING_METHODS constant in `test_openapi_boundaries.py:34` — that
# one reads from OpenAPI introspection (which lowercases methods).
# Wrong casing here would silently classify every mutating route as
# non-mutating and the test would pass vacuously.
MUTATING_METHODS = frozenset({"POST", "PATCH", "DELETE"})

MARKER_ATTRS = (ACTIVITY_ATTR, GATED_INLINE_ATTR, PUBLIC_ATTR)


def test_every_mutating_route_is_classified() -> None:
    # Canary: route_walker reaches into django-ninja internals
    # (api._routers, path_view.operations, op.view_func). If a future
    # ninja release renames any of those, the walker silently yields
    # zero and every assertion below passes vacuously. The pin in
    # backend/pyproject.toml (`django-ninja>=1.3,<2`) makes a major
    # bump deliberate; this floor catches a structural change within
    # the pinned range. Project had 97 mutating routes when this floor
    # was set — bump if that drops legitimately.
    mutating = [(m, p, v) for m, p, v in iter_operations(api) if m in MUTATING_METHODS]
    assert len(mutating) >= 50, (
        f"route_walker yielded only {len(mutating)} mutating routes — "
        "django-ninja internals may have shifted. See route_walker.py."
    )

    unclassified: list[str] = []
    for method, path, view in mutating:
        present = [name for name in MARKER_ATTRS if hasattr(view, name)]
        route_id = f"{method} {path} → {view.__module__}.{view.__qualname__}"

        # Belt-and-braces: a view double-stamped (e.g. both @requires
        # and @gated_inline by accident, or a copy-paste during the
        # migration) would silently pass a first-wins check. Make it
        # loud instead.
        assert len(present) <= 1, f"{route_id}: multiple markers {present}"

        if not present:
            unclassified.append(route_id)
            continue

        [marker] = present
        value = getattr(view, marker)
        if marker == PUBLIC_ATTR:
            assert isinstance(value, str), (
                f"{route_id}: @public_mutation reason must be a string"
            )
            assert value.strip(), f"{route_id}: empty @public_mutation reason"
        else:
            # isinstance, not `value in Activity` — StrEnum's `in`
            # accepts bare strings by value (3.12+), so the looser
            # check would let a hand-stamped
            # `_authz_activity = "catalog.edit"` pass.
            assert isinstance(value, Activity), (
                f"{route_id}: non-Activity marker value {value!r}"
            )

    assert not unclassified, (
        "Unclassified mutating routes (each needs @requires, "
        "@gated_inline, or @public_mutation):\n  " + "\n  ".join(unclassified)
    )


# Names that, when called as bare identifiers from a `@gated_inline`
# view body, count as the view fulfilling its enforcement contract.
# `enforce()` is the canonical choice (logs + raises); `check()` is
# acceptable when the route branches on the `Decision` (the documented
# reason for the inline carve-out).
#
# Codebase convention is bare-name imports (`from apps.core.authz.
# enforce import enforce`), so we only match `Name` calls — not
# `Attribute` calls like `something.check(...)`. The latter would
# match any object exposing a `.check()` method and silently pass
# routes that don't actually invoke the policy.
_POLICY_CALL_NAMES = frozenset({"enforce", "check"})


def _calls_policy(view: Callable[..., object]) -> bool:
    """True iff the view's source contains a bare call to enforce() or check().

    AST-level rather than substring so a stray comment or string
    literal mentioning ``enforce`` doesn't trick the check.

    Known limits — acceptable because the test's job is catching the
    obvious miss (the failure mode that produced the unverified-self-
    revert bug), not proving enforcement holds:

    1. **Indirection.** A view that delegates to a helper module which
       then calls ``enforce`` slips through. Closing that gap requires
       a runtime per-route 403 test.
    2. **Shadowed bare names.** A view that imports something else as
       ``check`` (e.g. ``from x import check``) and calls it would
       pass the AST match without invoking the policy. ``enforce`` is
       project-specific and unlikely to be shadowed; ``check`` is
       generic and the reviewer's burden is to confirm it's the
       policy ``check``.
    """
    try:
        source = inspect.getsource(view)
    except OSError, TypeError:
        return False
    # Top-level functions come back without leading indent; nested
    # defs (none today, but cheap to handle) come back with it.
    # Dedent so `ast.parse` accepts either shape.
    source = textwrap.dedent(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _POLICY_CALL_NAMES
        ):
            return True
    return False


def test_gated_inline_routes_call_enforce_or_check() -> None:
    """Every `@gated_inline` view must actually invoke the policy.

    `@gated_inline` is the documented carve-out for routes that load
    the target before evaluating the policy or branch on the
    `Decision`. Unlike `@requires`, the marker itself does NOT call
    `enforce()` — the view body is responsible for it. The
    route-inventory test above asserts the marker is present; this
    one asserts the view body actually does the work.

    Without this, a `@gated_inline` route can ship with no enforcement
    at all (the failure mode that produced the unverified-self-revert
    bug fixed alongside this test). The check is correct-but-coarse:
    it catches the obvious case where the view body has no policy
    call, and is blind to indirection through a helper module.
    """
    missing: list[str] = []
    for method, path, view in iter_operations(api):
        activity = get_gated_inline_activity(view)
        if activity is None:
            continue
        if not _calls_policy(view):
            missing.append(
                f"{method} {path} → {view.__module__}.{view.__qualname__} "
                f"(@gated_inline {activity.value})"
            )
    assert not missing, (
        "@gated_inline routes whose body never calls enforce()/check() — "
        "the marker is informational; the view body must invoke the "
        "policy or the route is silently ungated:\n  " + "\n  ".join(missing)
    )


# Activities whose mutating routes MUST carry @rate_limited (or
# @rate_limit_exempt). The mapping below dictates which bucket each
# activity charges — adding a new activity here forces every matching
# route to declare a bucket or an exemption, and is a deliberate policy
# decision rather than an emergent default.
EXPECTED_BUCKET_FOR_ACTIVITY: dict[Activity, RateLimitSpec] = {
    Activity.CATALOG_CREATE: CREATE_RATE_LIMIT_SPEC,
    Activity.CATALOG_EDIT: EDIT_RATE_LIMIT_SPEC,
    Activity.CATALOG_DELETE: DELETE_RATE_LIMIT_SPEC,
}


def _route_activity(view: object) -> Activity | None:
    """Return the rate-limit-relevant activity stamped on the view, if any.

    Walks both ``@requires`` and ``@gated_inline``. Today's relevant set
    (CATALOG_CREATE/EDIT/DELETE) only overlaps with ``@requires`` routes;
    consulting both anyway future-proofs us against adding e.g.
    CITATION_EDIT when some citation routes are gated inline.
    """
    return get_required_activity(view) or get_gated_inline_activity(view)


def test_rate_limit_relevant_routes_are_classified() -> None:
    """Every mutating route gated by a rate-limit-relevant activity
    must carry @rate_limited(spec) or @rate_limit_exempt(reason), and
    the spec must match the bucket the activity dictates.

    Mirrors ``test_every_mutating_route_is_classified`` — presence of a
    rate-limit marker on the route is mandatory; correctness of the
    bucket is mandatory too (catches the
    ``@rate_limited(CREATE_RATE_LIMIT_SPEC)``-on-an-edit-route typo).
    """
    unclassified: list[str] = []
    wrong_bucket: list[str] = []
    for method, path, view in iter_operations(api):
        if method not in MUTATING_METHODS:
            continue
        activity = _route_activity(view)
        if activity is None or activity not in EXPECTED_BUCKET_FOR_ACTIVITY:
            continue

        route_id = f"{method} {path} → {view.__module__}.{view.__qualname__}"
        spec = get_rate_limit_spec(view)
        exempt_reason = get_rate_limit_exempt_reason(view)

        if spec is None and exempt_reason is None:
            unclassified.append(f"{route_id} (activity={activity.value})")
            continue
        if spec is not None and exempt_reason is not None:
            wrong_bucket.append(
                f"{route_id}: route is both @rate_limited and "
                f"@rate_limit_exempt — pick one"
            )
            continue
        if spec is not None:
            expected = EXPECTED_BUCKET_FOR_ACTIVITY[activity]
            if spec != expected:
                wrong_bucket.append(
                    f"{route_id}: activity={activity.value} expects "
                    f"bucket={expected.bucket!r}, got bucket={spec.bucket!r}"
                )

    assert not unclassified, (
        "Rate-limit-relevant mutating routes missing @rate_limited / "
        "@rate_limit_exempt:\n  " + "\n  ".join(unclassified)
    )
    assert not wrong_bucket, (
        "Rate-limit bucket disagrees with route activity (or route is "
        "double-stamped):\n  " + "\n  ".join(wrong_bucket)
    )
