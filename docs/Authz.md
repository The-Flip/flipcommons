# Authorization

This document explains the project's authorization surface area: how the system
decides whether a user may perform a write, use an operational tool, or see an
authenticated UI affordance.

## Mental Model

Django is the source of truth for authz info. The frontend may hide or show
affordances from capability hints, but every mutation MUST be enforced by the
backend and may return a structured `policy_denied` 403.

Call sites ask whether a user may perform a named activity, such as
`catalog.edit` or `kiosk.edit`. The backend policy decides which user
attributes, roles, or target attributes matter for that activity.

Name activities for the action or surface being gated, not for the role
currently allowed to perform it. Prefer `kiosk.edit` or `django_admin.access`
over names that encode "superuser" or "staff".

NEVER add product gates by checking raw flags like `is_staff`, `is_superuser`,
or `email_verified` at the call site. Add or use an `Activity` instead.

## Adding Or Changing A Gate

1. Add or reuse an `Activity`.
2. Register the rule in the app that owns the activity. Cross-cutting rules live
   in `backend/apps/core/authz/rules.py`.
3. Classify every mutating route with `@requires`, `@gated_inline`, or
   `@public_mutation`.
4. Use frontend capabilities for UI affordances. Do not duplicate policy logic
   in Svelte.
5. If the API shape changes, run `make codegen`.
6. Run the relevant tests. At minimum, when markers or rules change, run
   `backend/apps/core/tests/test_route_inventory.py` and
   `backend/apps/core/tests/test_authz_registry_complete.py`. Target-aware
   predicates additionally need predicate tests and zero-query purity tests
   (see Policy Rules below).

## Policy Rules

Predicates return `Allow` or `Deny`, never `bool`. A denial carries a closed
`DenialCode` plus optional context so the API can return structured user-facing
errors.

Policy checks must be pure: no database queries, cache reads, network calls, or
other I/O. The caller is responsible for loading any data a rule needs before
calling the policy.

Target-aware predicates must read through a narrow Protocol defined beside the
rule. Keep those Protocols flat and scalar where possible, such as `user_id`
instead of `user`. Target-aware predicates need zero-query tests so serializer
capability loops cannot grow hidden N+1s.

## Capability Surfaces

Target-less capabilities are returned from `/api/auth/me/` and consumed through
`auth.can(activity)` in `$lib/auth.svelte`.

Target-aware capabilities are embedded on resource rows as a `capabilities` map,
for example `changeset.capabilities["changeset.undo"]`.

Capabilities are hints only. They reflect server state when the auth status or
row was fetched; a later mutation can still fail with `policy_denied` if user or
target state changed.

## Denials

`PolicyDeniedError` serializes as:

```json
{
  "detail": {
    "kind": "policy_denied",
    "message": "Verify your email address to continue.",
    "code": "verification_required",
    "context": {}
  }
}
```

The backend owns denial messages today. The frontend renders
`detail.message`; do not add a frontend denial-code mapper unless product
requirements grow beyond string messages.
