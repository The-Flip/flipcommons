# Authorization

## Problem

We need to be able to put checks around activity without wiring every call site to specific checks about who the user is.

Email verification -- [EmailVerification.md](EmailVerification.md) -- is the first concrete case: catalog edits should require a verified email so disposable email-password accounts cannot immediately write claims. But the authorization decision should not be named or modeled as "email verification" at every Svelte editor, API endpoint, or claims write helper. That would make the next constraint -- moderator role, account age, rate limit state, reputation, abuse flag, scoped delete permission, etc. -- require another audit of every edit path.

The product rule we care about is not "has verified email." It is "may perform this activity." Email verification is only one input into that decision.

## Proposal

Introduce a small policy/capability layer for user activities. Call sites ask whether a user may perform a named activity, and the centralized policy decides which checks currently apply.

Examples of activity names:

- `catalog.edit`
- `catalog.create`
- `catalog.delete`
- `claim.revert`

Backend write paths should depend on activity authorization, not directly on `email_verified`. For example, a catalog claim write should require `catalog.edit`; the policy for `catalog.edit` can initially require authentication, an active account, and verified email. Later, the same policy can add account-age, role, reputation, moderation, or rate-limit constraints without changing every catalog editor.

The frontend should follow the same language but must not reimplement the policy. The backend exposes capabilities through two surfaces, used together: a `/me/capabilities` endpoint for target-less activities (`catalog.create`), and per-resource capability hints embedded in resource responses for target-aware activities (`claim.revert` on a specific claim, `catalog.delete` on a specific entity). Both compute their answers via `policy.check`; neither is the sole source. Structured denial responses return stable blocker codes from a closed registry -- `verification_required`, `owner_required`, etc. -- with user-facing copy authored on the backend (in `core/authz/exceptions.py`) and rendered as-is by `parseApiError`. The wire shape (`code` + `context`) is structured so a future frontend mapper can override copy if product requirements ever justify one; today the backend is the single source for both decision and copy. See [Why no frontend mapper today](#why-no-frontend-mapper-today).

This is the standard policy-based / capability-based authorization shape: call sites request an action, central policy evaluates roles and attributes. For Flipcommons, a lightweight in-repo policy module is enough; adopting a full external authorization engine would be premature.

## Principles

- **Object-level-ready signature from day one.** The policy signature is `check(user, activity, target=None, context=None)`. Launch rules don't use `target` or `context`, but having the parameters present means later rules that need them (e.g. "you can revert your own claim but not someone else's", or "respect the rate-limit state middleware just computed") can be added without touching call sites.
- **Default-deny, single registry.** The registry of activities lives in one importable module, so the route-inventory test, the capabilities endpoint, and humans reading the codebase all see the same authoritative set. A missing rule is a programming error, not a permission grant: `check()` raises `LookupError` rather than returning `Deny`, so misconfiguration surfaces as a 500 with diagnostic context rather than a misleading 403. The registry-completeness test (`test_authz_registry_complete`) keeps that branch dead at runtime.
- **Pure decisions; no I/O in the policy.** `check` is a pure function over its inputs. The policy reads attributes on already-loaded objects; it does not query the DB, hit the cache, or call out to other services. New data dependencies are assembled by the caller (or by middleware that builds `context`) before the call. This keeps decisions cheap, testable without fixtures, and replayable from logs. Enforced statically by per-rule target Protocols and dynamically by a dev/test recording proxy — see [Enforcing pure decisions](#enforcing-pure-decisions). Corollary: serializers that embed capability hints must prefetch the attributes the policy reads, so the embed loop doesn't lazy-load behind the policy's back.
- **Decisions are structured, not boolean.** `check` returns either `Allow` or `Deny(code, context)` from the closed denial-code registry — never a bare bool. Throwing away the denial code at the boundary throws away the half of the answer that drives UX.
- **Anonymous users go through the policy.** The policy is invoked for unauthenticated requests too; they deny with `auth_required`. This means `/me/capabilities` works for logged-out callers (returning everything false) and the SPA doesn't branch on "logged in" before asking what's allowed. HTTP 401 stays reserved for "your session is invalid," not "you're signed out."
- **Mutations always go through the policy; reads are public by default.** Catalog reads, lookups, and search don't run through `policy.check` — there is no `catalog.read` activity. Authenticated-only reads (`/me`, drafts, notifications) gate on `is_authenticated`, not the policy. The exception: a small, deliberate set of sensitive reads (e.g. moderation tooling, ban audit trails, abuse-report inboxes) may be named as activities and gated, but only when the read is genuinely privileged. The default for new read endpoints is "no activity gate."
- **Backend is the source of truth; the frontend reflects.** Never mirror policy logic in JS. Two engines will drift.
- **Show affordances for capabilities the user can earn.** When a denial code points to a remediation the user can take themselves — `verification_required` (verify your email), `experience_required` (make more edits) — the SPA defaults to _showing_ the affordance and routing the denial to a remediation surface: a `/verify-email` page on click, a structured toast explaining "you need N edits, you have M" on submit. Hiding such affordances makes the SPA look identical to a logged-out view and erases the user's path to discovering what editing exists. Hide affordances only when the user has no path to gaining the capability themselves (a moderator-only action a regular user can't promote into; a banned account). Anonymous users sit in the middle: their remediation is sign-up, which the project surfaces through identity UI (`Nav`'s "Sign In" link) rather than per-affordance routing, so anonymous-vs-authenticated is the visibility split. See [Svelte.md's Authorization section](../../Svelte.md#authorization) for the implementation patterns (route-loader redirects vs. click guards).
- **Activities are product-meaningful, not data-model-shaped.** Resist granularity like `catalog.edit.title.scalar` -- that leaks the schema into the policy namespace and dissolves the abstraction.
- **Activities are named for what's being gated, not who can do it.** Don't name an activity after the role currently allowed (`moderation.action`, `admin.thing`) — roles change, the gated thing doesn't. The "thing" is usually an act the call site is performing (`entity.merge`, `claim.override`, `account.ban`), but it can also be a tooling surface (`django_admin.access`) or a user-state predicate (`rate_limit.exempt`); both are legitimate as long as the name describes what's gated, not the role permitted. Let the policy decide who qualifies. Add an activity when its call site is being built, not in advance.
- **Don't use Django's permission framework.** This activity layer is parallel to Django perms, not built on top. Per-model perms compose poorly with attribute checks (verified email, account age, rate limit), and we'd end up wrapping them anyway.
- **Denial codes are a closed enum.** One registry, mapped to user-facing copy. No ad-hoc strings spelled differently across editors.
- **Rate-limiting is policy-aware, not policy-owned.** Enforce early in the request path -- as early as the limit's scope allows (per-IP/per-user floods in middleware; activity- or target-scoped limits where the target is known). The policy may reflect rate-limit state for UX but is not the sole gate.

## Anti-goal: NO PERMISSION CHANGES other than email-verified

For the initial roll-out, the ONLY permission change we are making is requiring every CRUD operation to be email-verified. Do NOT change which users can do what, except for email-verified.

## Initial activities

The launch set. Each row is what the policy enforces today; later constraints (account age, reputation, rate limits, moderation flags) layer in without changing call sites.

| Activity         | Rules at launch                                  | Notes                                                                                                           |
| ---------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `catalog.edit`   | authenticated, active, email-verified            | Writes on existing entities.                                                                                    |
| `catalog.create` | authenticated, active, email-verified            | Separated from edit so creation can tighten independently later (e.g. account age) without touching edit paths. |
| `catalog.delete` | authenticated, active, email-verified            | Separated from edit so deletion can tighten independently later without touching edit paths.                    |
| `claim.revert`   | authenticated, active, email-verified            | Separated from edit so revert can tighten independently later without touching edit paths.                      |
| `changeset.undo` | authenticated, active, email-verified            | Inverts a delete-changeset (post-delete Undo toast). Target-aware: today scoped to the changeset author.        |
| `citation.edit`  | authenticated, active, email-verified            | Citation-source CRUD plus citation-instance writes attached to claims.                                          |
| `media.edit`     | authenticated, active, email-verified            | Upload, detach, set-primary, set-category — all media-attachment claim writes.                                  |
| `kiosk.edit`     | authenticated, active, email-verified, superuser | Kiosk config CRUD.                                                                                              |

- "Active" means `is_active=True` — the account is not currently deactivated for any reason (self-deactivation, dormant cleanup, etc.). Banning, when it ships, will be a separate predicate with a separate denial code so the SPA can render different copy.
- "Authenticated" means a logged-in session, not anonymous.

The four activities below the divider were added per "Add an activity when its call site is being built, not in advance" during the phase-1 inventory pass — same launch rules as the original four, separated only so each can tighten independently later.

## Decision shape

The policy entry point and its return type:

```python
def check(
    user: PolicyUser,              # Protocol covering both authenticated User and AnonymousUser
    activity: Activity,            # closed enum of registered activity names
    target: object | None = None,  # a record of the domain object the activity acts on, when applicable; per-rule predicates narrow this via their own Protocol (see Follow-ups)
    context: PolicyContext | None = None,  # caller-assembled ambient state (rate-limit, etc.)
) -> Decision: ...


@dataclass(frozen=True)
class Allow: ...

@dataclass(frozen=True)
class Deny:
    code: DenialCode             # closed enum
    context: Mapping[str, Any]   # shape declared per code

Decision = Allow | Deny
```

`Allow` and `Deny` are returned by the policy and serialized at the API boundary; the same shapes flow through both surfaces.

Individual predicates also return `Decision`, not `bool`. Each predicate names its own failure code (`is_authenticated` denies with `auth_required`, `is_active` with `account_deactivated`), which is what makes the [denial-code priority](#denial-code-priority) rule work — when multiple predicates fail, the evaluator picks the highest-priority `Deny`. A `bool`-returning predicate would discard the code and force the evaluator to reverse-engineer it, which can't be done correctly when the same predicate could plausibly fail for different reasons.

## Module layout

Per [AppBoundaries.md](../../AppBoundaries.md), the engine lives in `core` and per-app rule files register into a single central registry.

```text
backend/apps/core/authz/
  types.py        # Activity StrEnum, Decision, Allow, Deny, DenialCode enum, PolicyUser Protocol
  registry.py     # the activity registry + register() entry point
  predicates.py   # is_authenticated, is_active, email_verified, base Predicate
  evaluator.py    # check(user, activity, target, context) — the entry point
```

Per-app rule files declare each app's activities and rules:

```text
backend/apps/catalog/authz.py     # catalog.edit, catalog.create, catalog.delete
backend/apps/provenance/authz.py  # claim.revert
backend/apps/media/authz.py       # media.* activities
# etc.
```

Each app's `apps.py: ready()` imports its `authz` module so registration happens at startup. The route-inventory test then walks the populated registry and asserts every mutating route is mapped to a registered activity.

Core itself owns activities that aren't a single domain app's responsibility — user-state predicates like `rate_limit.exempt` and tooling-surface activities like `django_admin.access`. Because `core/authz/` is the engine package, those rules live in `core/authz/rules.py` (a sibling `apps/core/authz.py` would collide with the package) and `core/apps.py: ready()` imports it. New cross-cutting activities go there.

An activity registered without the `email_verified` predicate must add itself to `_ACTIVITIES_EXEMPT_FROM_EMAIL_VERIFIED` in `test_authz_registry_complete.py` with a per-activity comment explaining why; the docstring on `core/authz/rules.py` points there. The default is to require email verification — the policy module is the security boundary, and what it permits should be stated explicitly. The exemption list is short on purpose: today's only member is `django_admin.access`, which mirrors a Django-level gate that itself doesn't check email verification.

### Reading markers off views

The marker decorators (`@requires`, `@gated_inline`, `@public_mutation`) stamp string-keyed attributes (`_authz_activity`, etc.) on the view callable. Consumers must read those markers via the typed accessors in `core/authz/markers.py` rather than poking at the attributes directly:

```python
from apps.core.authz.markers import (
    get_required_activity,        # @requires      → Activity | None
    get_gated_inline_activity,    # @gated_inline  → Activity | None
    get_public_reason,            # @public_mutation → str | None
)
```

Each accessor wraps the `getattr(...)` lookup with an `isinstance` narrow, so the return type is genuinely correct (a hand-stamped `_authz_activity = "catalog.edit"` string returns `None` instead of silently impersonating an `Activity`). Future surfaces — `/me/capabilities` (Phase 7), embedded-hint serializers, capability pre-loaders — must use these accessors. The string constants `ACTIVITY_ATTR` / `GATED_INLINE_ATTR` / `PUBLIC_ATTR` are still exported for the route-inventory test, which legitimately enumerates marker names to detect double-stamping; nothing else should need them.

### Why `core`, not `accounts`

`core` is the right home because the engine is project-wide infrastructure with no dependencies, and every middle- and top-tier app calls into it. Putting it in `accounts` would invert the dependency direction — `accounts` is a peer of `core`, not a foundation under the rest of the project, and nothing currently imports from `accounts` (apps use `AUTH_USER_MODEL` strings for FKs). Authz isn't account-specific behavior; it's a gate that _reads_ user attributes.

The User-typing concern is handled by a small `PolicyUser` Protocol in `core/authz/types.py` declaring just the attributes the engine reads (`is_authenticated`, `is_active`, `email_verified`). The engine doesn't import the concrete `User` class.

### Why per-app rule files

Target-aware rules need to type-hint and read attributes from their app's models (a `Claim`, a `Title`, a `MediaAsset`). If those rules lived in `core`, `core` would have to import from every app above it, which the boundary rules forbid. Putting rules next to the models they care about — and registering them into a central registry — keeps `core` clean while the registry stays the single source of truth.

## Enforcing pure decisions

The "no I/O in the policy" principle is enforced primarily by per-rule target Protocols + mypy: the predicate's parameter is typed as a narrow Protocol, so reading any attribute outside that Protocol is a static type error caught at definition time. Tests that need to verify a target-aware predicate doesn't trigger a query wrap the call in Django's `CaptureQueriesContext` and assert the count is zero. No bespoke runtime infrastructure.

### Per-rule target Protocols

The engine's `target` parameter is generic (`Model | None`); each per-rule predicate declares its own narrower Protocol covering exactly the attributes that rule may read. The Protocol lives next to the predicate, in the consuming app:

```python
# apps/provenance/authz.py
from typing import Protocol

class ClaimPolicyView(Protocol):
    """The Claim attributes this app's policy is allowed to read."""
    @property
    def id(self) -> int: ...
    @property
    def author_id(self) -> int: ...
    @property
    def is_locked(self) -> bool: ...

def is_claim_author(user: PolicyUser, claim: ClaimPolicyView, context) -> Decision:
    if claim.author_id != user.id:
        return Deny(DenialCode.OWNER_REQUIRED)
    return Allow()

def claim_not_locked(user: PolicyUser, claim: ClaimPolicyView, context) -> Decision:
    if claim.is_locked:
        return Deny(DenialCode.ROLE_REQUIRED)
    return Allow()
```

Attributes are declared as `@property`, not variable annotations. Variable annotations in a Protocol are settable and invariant, which means a class exposing the attribute as a read-only property — or as a `Literal` class constant, like `AnonymousUser.is_active = False` — fails the structural match. `@property` makes the surface read-only and covariant, which is what we actually want: the policy reads, never writes, and a `Literal[False]` must be acceptable where `bool` is declared. The same convention applies to `PolicyUser` in `core/authz/types.py`.

Protocols are structural — `Claim` instances satisfy `ClaimPolicyView` automatically by having the right attributes — so the engine still passes real model instances at runtime; nothing about the call changes. The change is at the _predicate_ boundary: inside the predicate, the type checker sees only the Protocol's attributes. Writing `claim.author.is_moderator` is a static type error because `ClaimPolicyView` declares `author_id: int`, not `author: User`.

This makes "I want to traverse a relation" a visible policy decision: extending the Protocol is something a reviewer notices, and the diff shows the new attribute being added to the read surface. The Protocol also doubles as the contract for what serializers must `select_related` / `only(...)` when embedding capability hints — grep `ClaimPolicyView` to find the exact prefetch list.

The same pattern is used for `PolicyUser`: the engine declares the shared user surface (`is_authenticated`, `is_active`, `email_verified`); per-rule Protocols declare per-target surfaces.

### Verifying purity in tests

Static checking covers the typical mistake: reading an attribute outside the Protocol. It doesn't cover dynamic access (`getattr(claim, "author")` bypasses the type system) or a Protocol that declares a relation but the caller forgot to prefetch (the type checker is happy; runtime still N+1s).

**Every target-aware predicate must have at least one test that wraps the call in `CaptureQueriesContext` and asserts zero queries.** This is a hard rule, not a recommendation — without bespoke proxy infrastructure, this assertion is the only thing standing between "convention says predicates are pure" and "production N+1 inside a serializer loop."

```python
from django.db import connection
from django.test.utils import CaptureQueriesContext

def test_is_claim_author_is_pure(claim):
    with CaptureQueriesContext(connection) as ctx:
        decision = is_claim_author(user, claim, None)
    assert len(ctx) == 0, f"predicate ran {len(ctx)} queries"
    assert isinstance(decision, Allow)
```

`CaptureQueriesContext` is Django's canonical query-counting helper. The assertion documents the test's intent — "this predicate must be pure" — at the call site, rather than relying on a fixture that's easy to forget.

The `assert_predicate_is_pure(predicate, user, target=None, context=None)` helper lands with the **first target-aware predicate** (expected with the Phase 8 per-target rules — `is_claim_author` / `claim_not_locked`), not with Phase 4. Phase 4's only new predicate is `email_verified`, which is target-less; a target-less predicate's purity is already covered by the `is_authenticated` / `is_active` purity tests. Pre-extracting the helper in Phase 4 would design it for one shape (target-less), then need re-shaping when target-aware predicates arrive — better to defer.

## Denial responses

HTTP wire format on denial — nested under `detail` to match the project's structured-error idiom (see `ValidationErrorSchema` / `RateLimitErrorSchema` in `apps/core/schemas.py`):

```json
HTTP 403
{
  "detail": {
    "kind": "policy_denied",
    "message": "Verify your email to start editing.",
    "code": "verification_required",
    "context": { "email": "alice@example.com" }
  }
}
```

`message` is the user-facing copy the SPA renders today. `code` and `context` are on the wire so a future SPA mapper module can override copy per-code, but **no such mapper exists yet, and Phase 8 deliberately doesn't build one.** Each code's `context` shape is still part of the registry and part of the API contract; adding or removing a key is a breaking change.

### Why no frontend mapper today

The original design imagined a SPA module mapping `code → { title, body, primaryAction }`, rendered in place of the backend's `message`. On reflection, the mapper isn't justified yet for this codebase:

- **Single language.** No i18n requirements; the backend can author copy directly.
- **Single frontend.** No mobile client or third-party API consumer that would benefit from machine-readable codes over English strings.
- **No deploy-skew problem.** Backend and frontend ship together; copy changes don't need to outpace API changes.
- **No per-(route, code) UX yet.** The original argument for a mapper was richer-than-string structure (title/body/action button) and per-context overrides. The SPA today renders a flat error string in a toast; nothing consumes the richer structure.
- **Speculative scaffolding has a cost.** A mapper would duplicate the backend message registry, drift from it over time, and introduce a second source of truth for copy. CLAUDE.md is explicit about not building for hypothetical future requirements.

The simpler path: when a denial code needs `context`-aware copy (e.g. `experience_required`'s "you need 5 edits, you have 3"), the backend builds the message from `Deny.context` in `core/authz/exceptions.py`. Codes without context data use static `_DENIAL_MESSAGE` strings. `parseApiError` renders `detail.message`.

**When to revisit.** Build the mapper when at least one of these is true:

- (a) i18n lands and needs message keys;
- (b) the SPA grows richer-than-string error UI (action buttons, illustrated empty-states, per-context links) for at least two codes;
- (c) a non-SPA consumer needs structured codes that the backend's English copy can't serve. Until then, the wire shape (`code`, `context`) stays ready, the backend owns the copy, and `parseApiError`'s fall-through is the contract.

The parser's job stays "extract a message string." It already special-cases `validation_error` (which has field-level errors) and falls through to `plain(detail.message)` for every other structured error via the `StructuredErrorBodySchema` base contract. Adding a new structured error variant requires no parser change unless the variant has fields beyond the base.

All structured-detail flavors carry `kind` — `validation_error`, `rate_limit`, `policy_denied` — and the frontend extractor dispatches by `detail.kind`. New variants subclass `StructuredApiError` (declaring `kind` and `status` as class attributes plus a `to_body()` method) and declare a matching `kind` literal on their body schema; a single shared exception handler in `config/api.py` wraps the response.

Routes are not currently required to declare `403: PolicyDeniedSchema` specifically in their `response=` map. The global exception handler in `config/api.py` produces the structured body regardless, and `parse-api-error.ts` dispatches on `detail.kind` at runtime — so generic per-code rendering (today, the backend's `message` string) works without typed knowledge of which operations can deny.

There is a related but orthogonal contract: `test_post_patch_delete_declare_4xx_responses` requires every mutating endpoint to declare _some_ 4xx response (token presence, not comprehensive enumeration). For routes with input validation or missing-object lookups, 422 / 404 declarations satisfy that test, and policy 403 is left undeclared. For routes whose only error mode is the policy gate (today, just `create_config` in `apps/kiosk/api/configs.py`), the policy 403 is the natural — and currently the only — 4xx to declare; the union `PolicyDeniedSchema | ErrorDetailSchema` is used so a future inline `HttpError(403, "...")` would still type-check. Both shapes are fine; the 4xx-presence test does not care _which_ 4xx is declared, only that one is.

**Revisit if/when a frontend mapper lands.** Declaring `403` per route would buy a typed `error.detail.code` on the generated SvelteKit client, which only matters if the SPA grows _per-(route, code)_ special-casing — different copy or remediation for the same denial code depending on which operation produced it. Today the SPA has none of that. If the conditions in [Why no frontend mapper today](#why-no-frontend-mapper-today) flip and a mapper does ship, audit the SPA for per-(route, code) handling at that point: if it has emerged, sweep all `@requires` routes to declare `403: PolicyDeniedSchema` (or the union `PolicyDeniedSchema | ErrorDetailSchema` where an inline `HttpError(403, "...")` also fires) and add a route-inventory-style test that walks `@requires` markers and asserts each operation's response map declares 403. Otherwise, leave the contract as-is.

### Denial code priority

Multiple predicates can fail simultaneously (unverified email and deactivated account). The policy returns one code, not a list. The priority order is sorted by **actionability** — the code that tells the user the most useful thing first wins:

1. `auth_required` — user is anonymous
2. `account_deactivated` — `is_active` is false (self-deactivated, dormant cleanup, etc.)
3. `account_banned` — _(future)_ explicit ban; not in the `DenialCode` enum yet. Will be added when banning ships, separate from `account_deactivated` so the SPA can render different copy. Listed here to reserve the priority slot.
4. `role_required` — moderator/admin needed
5. `owner_required` — target row belongs to another user (e.g. undoing someone else's changeset)
6. `verification_required` — email not verified
7. `experience_required` — user hasn't accumulated the privilege threshold yet (e.g. reverting others' claims)
8. `rate_limited` — soft, retry possible

Telling a deactivated user to verify their email is the wrong UX; the priority order is what prevents that. The same logic puts `role_required` above `verification_required`: an unverified non-moderator who tries a moderator-only action should hear "moderator only," not "verify your email" — verifying won't grant them the access they're after, so the role message is the more useful one. `owner_required` sits between `role_required` and `verification_required` for the same reason — an unverified non-author trying to undo someone else's changeset should hear "not yours," not "verify your email" (verification won't grant ownership), but a future moderator-override path should still surface "moderator only" when relevant. `experience_required` sits below `verification_required` because verification is more actionable (one-click confirm vs. accumulate N edits) — an unverified user with too few edits should hear "verify your email" first. The order is global to the registry, not per-activity.

### Audit logging

Denials are logged at `info` with `(user_id, activity, code, target_id)`. Allows are logged at `debug` (mostly off in prod). Logging is the _caller's_ job — the policy returns a `Decision` and the calling middleware/decorator emits the log. Keeps the policy pure.

Logging is `enforce()`'s job specifically, not `check()`'s. Hot-path read sites — `/me/capabilities`, per-row capability hints in serializers, the rate-limit exemption query — call `check()` directly so they don't flood the audit channel with a record per row per request. Only paths that actually gate a request (the `@requires` decorator and `@gated_inline` view bodies) go through `enforce()`. The Phase 9 dashboard is keyed off enforcement-path records only; hot-path reads are deliberately invisible to it.

Tests that verify logging assert against a typed `CapturedAuthzLog` dataclass + pytest fixture in `apps/core/tests/test_authz_enforcement.py` — a small handler-based capture that pulls `extra=` keys off `LogRecord` into a typed shape. Future per-activity audit-log assertions should reuse the existing `authz_logs` fixture rather than reaching into `caplog.records[0].__dict__["activity"]` (which works at runtime but is `Any`-typed, so mypy can't catch a renamed `extra` key). The fixture documents the contract — every authz log record carries `(message, level, user_id, activity, code)` — and a missing key fails at fixture-translation time, not silently in a test that happens not to read it.

## Integration surface

The route-inventory test only works if there is one canonical way to gate a route. Static walking can see route signatures, dependencies, and decorators; it cannot see the body of a view function. If half the call sites use a Ninja dependency and half call `check()` inline, the inventory test is silently incomplete — which is the worst failure mode for a test whose job is catching missing gates.

### Canonical form: `@requires` decorator

Django Ninja does not have FastAPI-style dependency injection (`deps=` / `Depends`). The canonical gating form for this codebase is a Python decorator stacked directly under the route registration, the same shape Django's `@login_required` uses:

```python
# apps/catalog/api.py
@router.patch("/entities/{id}", auth=session_auth)
@requires(Activity.CATALOG_EDIT)
def patch_entity(request, id: int, ...): ...
```

`@requires(activity)` lives once in `core/authz/` and is **staged across two PRs**. Call sites apply the decorator the same way in both phases — only the decorator's body changes:

1. **Inventory phase**: `@requires` is a marker-only no-op. It stamps `_authz_activity = Activity.CATALOG_EDIT` on the wrapped view function so the inventory walker can see it without reading the body. No call into a policy module — the engine doesn't exist yet.
2. **Enforcement phase** (a later PR): `@requires`'s body is updated to also run `policy.check(request.user, activity, target=None)` and raise a structured 403 on deny. The marker stays. No call site changes.

This is what lets the inventory ship before the engine exists: applying the decorator everywhere is safe even when its body is a no-op, because the only side effect is the attribute stamp. See [Implementation phases](#implementation-phases) for the full PR sequence.

The decorator order matters: `@requires` must be _inside_ `@router.patch` so Ninja registers the wrapped callable. Reverse the stack and the marker sits on the Ninja-wrapped operation, not on the function the walker reaches via `Operation.view_func`.

### Constraints on wrapping decorators

Any decorator that wraps a Ninja-registered view — `@requires` today, plus any future variant (target-aware, async, dry-run, capability-hint pre-loader) — must rebuild the wrapper so it carries the _wrapped function's_ `__globals__`, not the decorator module's. A vanilla `@functools.wraps` wrapper will work for hand-written views and silently break factory-built ones.

Ninja resolves forward-ref annotations via `getattr(view, "__globals__", {})` (see `ninja.signature.utils.get_typed_signature`). It uses the wrapper's `__globals__` for forward-ref resolution, not the wrapped function's. A `@functools.wraps` wrapper carries the _decorator module's_ globals (e.g. `core/authz/markers.py`), so Ninja fails to resolve any annotation that lives in the wrapped function's module — most importantly, closure-scoped types in factory-built CRUD views (`data: request_body_schema` in `entity_crud.py`). The error surfaces as a pydantic `class-not-fully-defined` panic at OpenAPI generation, not at decoration time, so the decorator can sit in the codebase passing tests until the next `make api-gen`.

The fix is to rebuild the wrapper as a `types.FunctionType` carrying the wrapped function's `__globals__` while preserving the closure cells the body needs:

```python
def template(request, *args, **kwargs):
    _enforce(request.user, activity)   # closure cell
    return func(request, *args, **kwargs)

wrapper = types.FunctionType(
    template.__code__,
    func.__globals__,                   # the load-bearing swap
    name=template.__name__,
    argdefs=template.__defaults__,
    closure=template.__closure__,
)
functools.update_wrapper(wrapper, func) # copies __wrapped__/__signature__/etc.
```

Module globals referenced by the body (like `enforce`) must be captured as closure cells (`_enforce = enforce` in the enclosing scope) — once `__globals__` is the wrapped function's, the body's `LOAD_GLOBAL` lookups happen against it, and `enforce` isn't there.

`markers.py:requires` is the reference implementation. When a second wrapping decorator lands, extract a shared `wrap_view_preserving_globals(template, func)` helper at that point — not before.

### Documented exception: inline `check()`

A small set of routes legitimately can't fit the single-decorator form — they evaluate multiple activities, branch on the decision, or need to run the check after mutation-context loading. These call `check()` inline, but **carry an explicit marker** so the inventory test still recognizes them as gated:

```python
@router.post("/claims/{id}/revert", auth=session_auth)
@gated_inline(Activity.CLAIM_REVERT)
def revert_claim(request, id: int, ...):
    claim = get_object_or_404(Claim, id=id)
    decision = check(request.user, Activity.CLAIM_REVERT, target=claim)
    if isinstance(decision, Deny): raise PolicyDenied(decision)
    ...
```

The `@gated_inline` decorator is informational — it does not run the policy itself (the inline `check()` does that). Its only job is to declare the activity to the inventory test. Inline gating is the exception, not the default; if a route can use `@requires()`, it should.

### Public-mutation allowlist

Some mutating routes legitimately have no activity gate — anonymous signup, password reset, contact form. Being ungated is a positive declaration, not the absence of one:

```python
@router.post("/auth/signup", auth=None)
@public_mutation("anonymous account creation by design")
def signup(request, ...): ...
```

`@public_mutation(reason)` records the route in the inventory as deliberately-public; the reason string is captured in the inventory output so a future reviewer can audit "do we still want this public?"

### Route-inventory test

A pytest walks every Ninja router in the project and classifies each mutating operation by the markers above:

- `@requires(Activity.X)` decorator → gated, mapped to `X`
- `@gated_inline(Activity.X)` decorator → gated, mapped to `X` (manual `check()` in body)
- `@public_mutation(reason)` decorator → deliberately ungated, with reason captured
- none of the above → **test failure**, with the route path in the message

A mutating route that lacks any marker fails the test. There is no `# noqa`. The list of activities the test recognizes is read from the central registry, so the test and the policy share one source of truth.

## Surfaces to classify

Every authenticated mutating backend route must carry one of the markers above (`@requires`, `@gated_inline`, or `@public_mutation`). The inventory PR lands these markers as no-ops and the route-inventory test asserts the classification is exhaustive. Enforcement — flipping `@requires` from no-op to "call `policy.check` and raise on deny" — is a separate, later PR; until then, marker presence is the only commitment. See [Implementation phases](#implementation-phases) below.

Known surfaces include:

- catalog claim writes
- catalog creates, deletes, and restores
- claim revert and changeset undo
- media upload, detach, category, and primary-image mutations
- citation source, link, extraction, and citation-instance mutations
- kiosk config mutations
- factory-registered CRUD routes

Keep the exhaustive route inventory in code or tests, not this document, so it can be mechanically checked instead of going stale.

## Implementation phases

The design ships across a sequence of small commits. Each is independently mergeable; the first three are intentionally no-ops on user-visible behavior, and from Phase 4 onward each phase lights up one specific user-facing change (email gate, denial copy, target-less affordances, per-row affordances).

Each commit's acceptance criterion is small enough to bisect cleanly: commit 1 is "inventory test passes," commit 2 is "engine unit tests pass," commit 3 is "every authenticated user can still do everything they could yesterday," and so on.

### 1. ✅ DONE: Inventory + markers (no enforcement)

Add `@requires`, `@gated_inline`, `@public_mutation` as marker-only no-ops in `core/authz/`. Apply across every mutating route. Land the route-inventory test that asserts every mutating operation carries one of the three markers. No engine module yet; no behavior change.

### 2. ✅ DONE: Engine module

Build `core/authz/` proper: `Decision` / `Allow` / `Deny`, `DenialCode` enum, registry, predicate composition, `PolicyUser` Protocol, evaluator, and per-app `authz.py` rule files registering each launch activity with `authenticated + active` rules. Pure unit tests, no integration. `@requires` is still a no-op; `policy.check` exists but nothing calls it from a request path.

### 3. ✅ DONE: Enforcement flip

Update `@requires`'s body to call `policy.check` and raise a structured 403 on deny. (`@gated_inline` stays stamp-only — its routes already call `check()` inline; flipping the marker would double-evaluate.) Launch rules are still `authenticated + active`, so behavior is unchanged from today (every authenticated user passes). This is the moment "the gate is on" with zero user-visible diff.

### 4. ✅ DONE: Email verification gate

([EmailVerification.md](EmailVerification.md)). Add `email_verified` column to `User`, wire it into the mirrored-fields refresh, add the `email_verified` predicate to each launch activity's rule. Now the gate actually slows spam.

### ✅ DONE: 6a. Role predicates

Add `is_staff` and `is_superuser` predicates to `core/authz/predicates.py` with the `role_required` denial code (already in the priority list). Foundational only — no call sites consume them yet, so behavior is unchanged. Lands as its own commit so the predicate API can be reviewed without being bundled with the kiosk and rate-limit refactors that depend on it.

### ✅ DONE: 6b. Kiosk: fold superuser check into the policy

Fold `is_superuser` into `KIOSK_EDIT`'s rule; remove the inline `_require_superuser` helper from `apps/kiosk/api/configs.py`. Behavior unchanged — the policy verdict matches the inline helper.

### ✅ DONE: 6c. Rate-limit exemption via the policy

Add a `rate_limit.exempt` activity registered with `is_staff`. Update `provenance/rate_limits.py` to call `policy.check(user, Activity.RATE_LIMIT_EXEMPT)` instead of reading `user.is_staff` directly. After this, the rate limiter never reads role flags directly — the policy is the single source of truth for _who qualifies_.

Update the module docstring at the top of `rate_limits.py` (currently "Staff (`user.is_staff`) bypass all limits") to describe the new mechanism — exemption is decided by `rate_limit.exempt`, which today resolves to `is_staff` but is no longer the file's concern. A reader who learns the mechanism from the docstring should not then go looking for `is_staff` reads in this file.

`rate_limit.exempt` happens to have no route and no current UI consumer, but it's a plain Activity with no special-case flag. The route-inventory test walks routes → registry, not the reverse, so an activity without a route causes no failure. `/me/capabilities` returns it like any other; the SPA ignores capabilities it doesn't consult, and a future client could legitimately use this verdict to skip optimistic-throttle UI. If a future activity ever needs to be hidden from `/me/capabilities` for a substantive reason (e.g. a sensitive-moderation activity whose existence in the response would leak info), add the filter then.

#### Scope notes for Phase 6 (a/b/c)

`AuthStatusSchema.is_superuser` and the `is_superuser` redirect in `frontend/src/routes/kiosk/edit/+layout.server.ts` remain until Phase 7 lands `/me/capabilities` — removing them earlier would leave the SPA without a signal for the kiosk-edit affordance.

Out of scope: the `is_staff`/`is_superuser` check in `accounts/api.py` WorkOS auto-link (a privilege-hijack safety guard, not a permission gate — stays as raw flag checks).

### ✅ DONE: 7. Sync capabilities to front end + AuthStatusSchema cleanup

Backend + frontend changes for the target-less capabilities surface. Capabilities ride on the existing `AuthStatusSchema` returned by `/api/auth/me/` — adding a separate `/me/capabilities` endpoint was considered and rejected: one round-trip on cold start, one source of auth identity + verdicts, no new SSR plumbing. Anonymous callers get an all-false map (every rule's first predicate is `is_authenticated`, so the policy denies them naturally).

**Wire shape.** `AuthStatusSchema.capabilities: dict[Activity, bool]`, populated server-side by walking `iter_rules()` and skipping any rule marked `target_aware=True`. `Activity` is exported as a string-literal union in the generated TS schema. Codegen renders the field as `{ [key: string]: boolean }` (pydantic emits `additionalProperties: boolean`); the SPA stores it internally as `Partial<Record<Activity, boolean>>` so the call site `auth.can(activity)` keeps a typed-key check. New activities flow through automatically — adding to the `Activity` enum and registering a rule is the only change required.

**Registry: `target_aware` flag.** A new `register(activity, *predicates, target_aware=False)` kwarg on the registry. `claim.revert` and `changeset.undo` are marked `target_aware=True` from day one — Phase 8 wires their per-row hints, but reserving the keys now keeps the wire shape stable across the boundary. `compute_capability_map(user)` (in `core/authz/capabilities.py`) is the helper that walks the registry and applies the filter; `/me/` calls it via `policy_user(request.user)`.

**`policy_user()` boundary cast** (extracted in this phase per the "extract on second use" rule — see Phase 8's note below). Inline `check()` callers pass `request.user`, typed `AbstractBaseUser | AnonymousUser`, which doesn't structurally satisfy `PolicyUser`. The helper centralizes the unavoidable cast; `provenance/rate_limits.py` migrates off its inline `cast(PolicyUser, user)` to use it.

**New activity: `django_admin.access`** (rule: `is_authenticated, is_staff`). Django admin's `/djadmin/` is staff-gated by the framework itself; this activity exists so the SPA can decide whether to render the "Django Admin" nav link without the schema needing to expose the underlying flag. The activity is named for the surface it gates, not the role permitted (see ["Activities are named for what's being gated, not who can do it"](#principles)). Registers in `core/authz/rules.py` and is listed in `_ACTIVITIES_EXEMPT_FROM_EMAIL_VERIFIED` in `test_authz_registry_complete.py` so the email-verified pin doesn't reject it — the SPA nav link mirrors what Django actually allows, and Django allows unverified staff to reach `/djadmin/`.

**Tightening `rate_limit.exempt`.** The Phase 6c registration was `is_staff`. Phase 7 tightens it to `is_authenticated, email_verified, is_staff`. The policy module is the security boundary; what it permits should be stated explicitly, not inferred from whatever upstream gate happens to fire first. Rate-limit exemption is a privilege we only grant to verified staff — say it. (`is_authenticated` is also added so anonymous surfaces `AUTH_REQUIRED` rather than `ROLE_REQUIRED` in the denial code; same convention applies to every rule in `core/authz/rules.py`.)

**Frontend: capability-aware auth store.** `auth.svelte.ts` gains `capabilities`, `can(activity)`, and `refresh()`. `refresh()` re-fetches `/me/` bypassing the `loaded` gate that `load()` honours; concurrent calls de-dupe via an in-flight promise so a burst of `policy_denied` 403s on a list page fires one `/me/` round-trip, not N. `isSuperuser` and `set()`'s `is_superuser` parameter are removed.

**403-as-invalidation.** An `onResponse` middleware in `client.ts` watches for `403` with `detail.kind === 'policy_denied'` and fires a registered callback — the auth store registers `auth.refresh()` at module init, browser-only. The middleware uses a registration setter (`registerOnPolicyDenied`) rather than a static import of `auth` to avoid a `client → auth → client` cycle. This catches the **allow→deny** drift direction only (capability tightened mid-session). The reverse direction (capability newly granted) is covered today only by natural page reload after the WorkOS callback, which reinitializes the `auth` module singleton. There are no in-SPA login/signup/email-verify handlers in this codebase — those flows happen at WorkOS, and the user lands back via a server-side callback that creates a fresh session. If an in-app verify flow ever lands, it must call `auth.refresh()` to refresh the store mid-session. Cross-tab capability changes are not covered today; revisit with `BroadcastChannel` if Phase 9 telemetry shows it matters.

**Frontend migrations.**

- `frontend/src/routes/kiosk/edit/+layout.server.ts` — redirect now reads `data.capabilities?.['kiosk.edit']`. Anonymous redirect to `/login` stays unchanged.
- `frontend/src/lib/components/Nav.svelte` — admin section split into per-link gates: `auth.can('kiosk.edit')` for "Kiosks", `auth.can('django_admin.access')` for "Django Admin"; section visibility on either. This is what makes `django_admin.access` worth introducing — without it, dropping `is_superuser` would force the Nav to keep reading some other flag for the admin row.
- `frontend/src/lib/auth.svelte.ts` — `isSuperuser` and `set()`'s `is_superuser` removed. Migrated before the schema field so TypeScript flagged any straggling reader.
- Test fixtures (`Nav.dom.test.ts`, `kiosk/edit/layout-server.test.ts`) drive capability state instead of `is_superuser`.

**Audit before removing the schema field.** After the named migrations landed, grep on `frontend/` for `is_superuser` / `isSuperuser` reads returned zero hits. The named migrations covered every consumer.

**OpenAPI naming allowlist.** Pydantic emits `Activity` as a top-level component schema (the `StrEnum` is referenced as a `dict[Activity, bool]` key), which trips the `*Schema`/`*Ref` suffix discipline. `Activity` is added to `ALLOWED_BARE_NAMES` in `test_openapi_boundaries.py` rather than renamed — `ActivitySchema` would lie about the type's role.

This is the phase that lets target-less affordances (create buttons, top-level New entries, Nav rows) gate on policy verdicts instead of role flags or "are they logged in."

### ✅ DONE: 8. Per-resource capabilities

This phase introduces target-aware rules by codifying one rule that already exists imperatively in the codebase: `changeset.undo`'s author scoping. **This is not a tightening or changing of what a user can do** — every user who can undo today can undo after Phase 8, with identical constraints. The change is structural: the rule moves from imperative code into the policy module, and the SPA gains per-row verdicts so it can render the Undo affordance correctly instead of showing it for changesets the user can't actually undo.

`changeset.undo` is target-aware because the verdict depends on both the user and the specific changeset (you can undo your own; you can't undo someone else's). The activities table notes the rule is "scoped to the changeset author." Phase 8 expresses the author-scoping as a target-aware predicate (`is_changeset_author`) on top of `authenticated, active, email_verified`.

#### `claim.revert`'s edit-count rule is deliberately not lifted

`claim.revert` has a target-aware rule today — [`execute_revert` in `apps/provenance/revert.py`](../../../backend/apps/provenance/revert.py) raises a 403 when reverting another user's claim if the caller has fewer than `REVERT_OTHERS_MIN_EDITS = 5` prior edits, and reverting your own claim has no threshold. Phase 8 leaves this rule imperative. Two reasons:

1. **Engine purity vs. premature trust design.** A `has_min_edits(n)` predicate would either query `ChangeSet.objects.filter(user=user).count()` (violates the [no-I/O principle](#principles)) or read a denormalized signal off the user — `is_established_editor` bool, `edit_count` int, cached `TrustProfile`, JSONField, etc. Picking among those requires committing to a trust-signal shape before there's enough product clarity to choose. The next trust-shaped rules (account age, voting weight, etc.) will tell us what the right storage and shape are; Phase 8 isn't the time to guess.
2. **The 403 is a feature, not a bug.** Showing the Revert button to a user who hasn't yet earned the privilege — and explaining "you need 5 edits before you can revert others' changes — you have 3" through a structured denial whose copy is built from `context` on the backend — is a better UX than hiding the affordance. It surfaces what functionality exists, gives users a concrete target, and converts policy denials into engagement signals. This is the gamification shape the product wants.

Revisit when a second trust-shaped rule lands. With two concrete signals to design against, the right answer for trust storage and predicate shape falls out of real requirements instead of being chosen speculatively. Until then, the imperative check in `revert.py` is the source of truth for the edit-count rule, and `claim.revert`'s policy stays at `authenticated, active, email_verified`.

`claim.revert` stays registered with `target_aware=True` (per [Phase 7's wire-shape reservation](#-done-7-sync-capabilities-to-front-end--authstatusschema-cleanup)) even though its current policy rule reads no target attributes. This keeps `claim.revert` out of `/me/capabilities` and reserves a per-row slot in `ClaimSchema` against the future lift, so adding `is_claim_author` + a trust predicate later doesn't shift the wire shape. A reader checking "rule is target-less, why is the flag set?" should find that answer here, not change the flag.

The lifted rule is existing behavior; the [anti-goal](#anti-goal-no-permission-changes-other-than-email-verified) ("ONLY permission change is email-verified") still holds.

#### Structured denial for the imperative edit-count check

The "the 403 is a feature" rationale above only pays off when the SPA can render specific copy — "you need 5 edits before you can revert others' changes — you have 3," not a generic "Forbidden" toast. The imperative check in `revert.py` today raises `HttpError(403, "...")` with no denial code and no `context`, and the rendered message is a flat string. Phase 8 closes the gap by making the wire structured and authoring the user-facing copy on the backend (see [Why no frontend mapper today](#why-no-frontend-mapper-today)):

- Add `DenialCode.EXPERIENCE_REQUIRED` to the closed enum. The name describes the product concept (the user hasn't earned the privilege yet) rather than the mechanism (edit count), so a later rule change to "edits + account age + voting weight" doesn't force a rename.
- Slot it into the [denial-code priority](#denial-code-priority) between `verification_required` and `rate_limited`. The actionability ladder: verify your email (immediate), earn the experience (sustained activity), wait out a rate limit (short-term).
- Update `revert.py` to raise a structured `PolicyDenied(DenialCode.EXPERIENCE_REQUIRED, context={"required": REVERT_OTHERS_MIN_EDITS, "current": edit_count})` instead of bare `HttpError`. Same 403, same imperative location, structured shape.
- In `core/authz/exceptions.py`, add a context-aware message builder for `EXPERIENCE_REQUIRED` so `parseApiError`'s `detail.message` renders "You need {required} edits before you can revert others' changes — you have {current}." The wire still carries `code` and `context` for a future SPA mapper, but the rendered copy lives with the backend decision.

This is small (one enum value, one priority-list slot, one structured raise, one message-builder entry) but load-bearing for the gamification claim.

#### Ships

- The first per-target Protocol and predicate: `ChangeSetPolicyView` + `is_changeset_author` for `changeset.undo`. (`ClaimPolicyView` and claim-target predicates are deferred along with the edit-count rule above.)
- The `assert_predicate_is_pure(predicate, user, target, context)` test helper, designed against the target-aware shape (see [Verifying purity in tests](#verifying-purity-in-tests)).
- The `target=` kwarg on `register()`, declaring each target-aware rule's Protocol type so a system check can validate schema/activity pairings at startup.
- A `capabilities: dict[Activity, bool]` field on `ChangeSetSchema`, populated per row by calling `policy.check(user, Activity.CHANGESET_UNDO, target=cs)`. `ChangeSetPolicyView` reads only `id` and `user_id` (both columns on the row itself), so no prefetch helper is needed; the meta-test below catches it if a future Protocol change introduces a relation.

#### Wire shape

The per-row field is named `capabilities`, mirroring `AuthStatusSchema.capabilities` from Phase 7 so the SPA learns one word for "policy verdicts" and applies it in two places. Its type is `dict[Activity, bool]`; the same TypeScript type as Phase 7. Example, on a changeset:

```json
{
  "id": 456,
  "note": "...",
  "capabilities": { "changeset.undo": true }
}
```

**Each schema declares its policy activities explicitly.** A schema lists the activities it embeds as `policy_activities: ClassVar[list[Activity]] = [Activity.CHANGESET_UNDO]`. `ClassVar` is required so pydantic doesn't sweep the attribute into the model's field set. That single list drives the verdict loop's wire output; pairing it with `policy_target_model: ClassVar[type[Model]] = ChangeSet` lets the system check validate Protocol/model conformance at startup. One grep-able source of truth per schema.

The registry's job here is validation, not enumeration. The validation runs as a Django system check in `core/authz/checks.py` (registered with `@register(Tags.models)`, the same pattern as `check_linkable_models`), so it fires at `manage.py check` and at server boot. For each schema's `policy_activities` entry, the check asserts the activity's registered target Protocol is structurally satisfied by the schema's underlying model. Putting `Activity.CHANGESET_UNDO` on `TitleSchema` fails the check because Title has no `user_id`. The cost is one new kwarg on `register()`: `register(Activity.CHANGESET_UNDO, ..., target_aware=True, target=ChangeSetPolicyView)` — declaring the target Protocol explicitly is what makes the startup check possible.

This is a presence check, not a semantic one. Structural Protocol matching verifies attribute _names and declared types_ on the model, not meaning — a model with an unrelated `user_id` field would pass. The real safety is the schema author explicitly declaring `policy_activities`; the system check is a coarse smoke test that catches gross mispairings (wrong schema, copy-paste error) at boot rather than at request time.

We considered a "registry auto-matches by Protocol" approach (`iter_activities_for_target(T)` walking every registered target Protocol and returning matches) and rejected it. `runtime_checkable` Protocol matching checks attribute _presence_, not types or semantics, so any model with `id` and `user_id` structurally satisfies `ChangeSetPolicyView` — and the failure mode is a wrong verdict on the wire, which is the worst place for it. Phase 8 ships a single embedding schema; "register a new activity, add it to the schema's list" is rounding-error maintenance compared to killing the structural-match path.

**Nested rows carry the same shape as standalone.** If a list endpoint returns changesets — top-level or nested under another resource — each row carries its own `capabilities` map populated by the same serializer logic. Same shape whether fetched top-level or embedded; the SPA reads `changeset.capabilities['changeset.undo']` either way. Per-row verdicts can legitimately differ across rows (you authored some changesets but not others) — aggregate summaries on the parent would collapse that information and defeat the point of target-aware rules.

**Target-less activities never appear on rows.** A `Claim` row never carries `catalog.create`; that verdict lives only on `auth.capabilities` (Phase 7). One activity, one home. This prevents a target-less verdict from having two on-the-wire copies that can disagree if any one of them goes stale.

#### Keeping prefetches in sync with the Protocol

The policy reads attributes off already-loaded objects, so any serializer that embeds a hint must have the attributes the relevant `*PolicyView` Protocol declares loaded before the embed loop runs, or the loop will N+1 behind the policy's back. Two design pressures keep this honest at the call-site level:

- **Protocols stay flat.** Target Protocols declare scalar attributes only — `author_id: int`, never `author: User`. Phase 8's `ChangeSetPolicyView` follows this convention. Flat attributes are columns on the row itself, so the default queryset already has them; no `select_related` is required. The same convention is what makes the [purity discipline](#enforcing-pure-decisions) statically checkable.
- **Meta-test backstop.** A single pytest finds every serializer with a `capabilities` field, exercises its list endpoint at two different row counts (e.g. N=2 and N=20), and asserts `queries(N=20) - queries(N=2) == 0`. Scope is narrow on purpose: it catches the embed-loop N+1 (which is row-scaling by construction) and nothing else. Constant overhead — a fixed 47-query waste that's bad but doesn't grow with rows — is a different bug class and belongs in each endpoint's own query-count regression test, where the budget is meaningful and the failure message is actionable.

A future Protocol that legitimately needs to traverse a relation will demand a prefetch helper. Phase 8 deliberately doesn't ship one speculatively — the first relation-traversing Protocol introduces the helper with a concrete API shaped by its real call site.

#### Staleness

Embedded hints reflect server state at response time only. User-state drift (the user's email got unverified, their account got deactivated) is caught by the Phase 7 403-as-invalidation middleware. Target-state drift (a claim got locked after the row was fetched, an entity got soft-deleted) is _not_ — the 403 still fires correctly when the user clicks the now-stale affordance, and the SPA's generic `policy_denied` toast is the user-facing fallback. Per-row invalidation (websocket push, refresh-on-focus) is out of scope for Phase 8; revisit if Phase 9 telemetry shows target-state drift produces a meaningful 403 rate. The embedded hint is a UX optimization; the 403 is the real gate.

### ✅ DONE: 9. Documentation

Document the authorization surface area for future contributors and agents.
The stable contributor reference is now [`docs/Authz.md`](../../Authz.md), with
targeted guidance in [`docs/Svelte.md`](../../Svelte.md),
[`docs/Reviewing.md`](../../Reviewing.md), [`docs/ApiDesign.md`](../../ApiDesign.md),
and [`docs/AGENTS.src.md`](../../AGENTS.src.md) (regenerated into `CLAUDE.md` /
`AGENTS.md`).

### 10. Observability

Stand up a denial-rate dashboard keyed off the audit-log records emitted since Phase 3 (`(user_id, activity, code, target_id)`). Group by `activity` and `code` so that an unexpected cohort hitting `verification_required`, a route that started 403'ing after a rule tightened, or a sudden `role_required` spike are all visible without trawling logs. Lands last because earlier phases are what _generate_ the signal worth watching; running this earlier would dashboard a near-empty stream.

The dashboard is the on-call backstop for any future rule tightening (account-age, reputation, rate-limit-as-policy) — those changes are easier to ship safely once denial rates are observable in aggregate. This is also the natural place to revisit whether dry-run mode (currently deferred) is worth building before the next rule change.

## Follow-ups

### ✅ DONE: Enforce `claim.revert` policy in the route, not just `execute_revert`

`apps/provenance/api.py:revert_claim` carries `@gated_inline(Activity.CLAIM_REVERT)` but never calls `enforce()`. The `auth=django_auth` layer covers `is_authenticated` + `is_active`, and `execute_revert` covers the imperative `experience_required` check, but **nothing enforces `email_verified`** — an unverified user can revert their own claims today, in violation of the [anti-goal](#anti-goal-no-permission-changes-other-than-email-verified) and of `claim.revert`'s registered rule.

Fix: after loading the `Claim`, add `enforce(policy_user(user), Activity.CLAIM_REVERT, target=claim)` to `revert_claim` (same shape as `undo_changeset` already does). Add a failing endpoint test for an unverified self-revert returning structured `verification_required` first, per the TDD rule.

### ✅ DONE: Gate frontend edit affordances at the destination, not the affordance

The original framing of this follow-up — "migrate `auth.isAuthenticated` edit-affordance gates to `auth.can(...)`" — was reversed in implementation (commits `ad6f091cd`, `ee6c9ebde`). The shipped design **shows affordances to all authenticated users for discoverability** and moves the policy gate to the click destination:

- **Route loaders** (`*/edit`, `*/new`) call `requireCapability(fetch, activity)` — redirects unverified users to `/verify-email`, anonymous to `/login`. Edit gates live in `+layout.ts` so `[section]` subroutes are also covered on direct navigation.
- **Inline action buttons** (e.g. `EditHistory`'s Revert) submit unconditionally and let the structured `policy_denied` 403 carry remediation copy. Target-aware activities like `claim.revert` are absent from `/me/` capabilities by design, so `auth.can()` would always return false and gate everyone.

Under this design, `auth.isAuthenticated` is the correct visibility signal — it gates discoverability (anonymous users hide; their remediation is sign-up in `Nav`), not permission. See [docs/Svelte.md `## Authorization`](../../Svelte.md#authorization) for the contributor-facing rules.

The originally-flagged regression-class concern (an ESLint guard against `auth.isAuthenticated &&` patterns) is moot under the shipped design — the pattern is now correct.

### Type-constrain `check()` / `enforce()` target to the activity's target Protocol

Today both functions type `target` as `object | None` because `Activity` is a flat `StrEnum` with no type info — there's no way to say "this activity's target must satisfy `ChangeSetPolicyView`" at the engine boundary. Per-rule predicates narrow via their own Protocol parameter, but the engine can't statically constrain what callers pass. The fix would let `check(activity, target)` reject wrong-shaped targets at mypy time and remove the `object | None` smell at the boundary.

**Don't design this with one Protocol.** As of this writing `ChangeSetPolicyView` is the only target Protocol in the codebase, and Python's `StrEnum` doesn't compose naturally with `Generic[T]` — the design space forks into meaningfully different shapes (parameterized `Activity[T]`, a sibling `TargetedActivity[T]`, a typed `register_for(T)` builder, a dataclass-valued enum, etc.), each with different implications for the wire `value` contract, audit-log shape, and the kinds of misuse mypy can catch. Picking among those on the basis of a single example would almost certainly produce an abstraction that doesn't fit the second case.

**Trigger:** revisit when a second target Protocol concretely exists (e.g. `ClaimPolicyView` if the edit-count rule is ever lifted; some other per-resource Protocol from a future feature). Two concrete examples is the minimum sample size to make this design choice honestly.

## Deferred / non-goals

- **Dry-run mode for rule changes.** Once the launch rules are in place, tightening one (e.g. adding an account-age requirement to `catalog.create`) risks 403'ing active users mid-session. The usual answer is a dry-run pass that returns the would-be decision in a header without enforcing, then flip after one deploy cycle. Not needed pre-launch; the pure-decision design makes this easy to add later.
- **Bulk / batch evaluation API.** Per-target capability hints in list responses are 50× `policy.check` calls per render. With pure decisions and prefetched attributes that's cheap; if a profiler ever disagrees, add a `check_many` helper. Not worth designing speculatively.
- **3rd party authorization engine** (OPA, Cedar, Oso). The shape of this design is compatible with a future port, but the in-repo policy module is the right size for Flipcommons today.

## Alternatives considered

Rather than building our own auth engine, we considered and rejected the following approaches:

- **django-rules.** The closest existing fit in the Python/Django ecosystem: predicate-based, composable with `&` / `|` / `~`, default-deny, object-level support, pure-function model. Maps onto most of the principles above. Rejected because it returns `bool`, so the structured-decision contract — typed `Decision`, denial-code priority order, per-code `context` shape — would have to be built as a wrapper of comparable size to writing the engine ourselves. Secondary concern: the natural call site (`user.has_perm("catalog.edit")`) reads as Django's permission framework even though django-rules sidesteps the underlying `ContentType` machinery, which invites the confusion we're explicitly trying to avoid. A ~150-LOC in-repo module is the simpler answer at our scale.
- **django-guardian.** Per-object permissions via DB rows. Wrong shape — our launch rules are attribute checks (verified email, active account), not row-level grants, and persisting per-(user, object) rows would be a denormalized mirror of attributes that already live on the user.
- **Casbin / py-abac / Vakt.** General-purpose RBAC/ABAC engines with external policy files or DSLs. Heavier than the problem; the policy file becomes a second source of truth that has to stay in sync with the activity registry.
- **Oso (open-source).** Was the obvious pick a few years ago; the company has deprioritized the OSS library in favor of a hosted product. Not a stable bet.
- **Django's built-in permission framework + `ContentType` perms.** Already excluded by a principle above; restated here for completeness — per-model perms compose poorly with attribute checks, and we'd end up wrapping them.
