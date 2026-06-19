"""Phase-3 enforcement tests: ``enforce()`` + ``@requires`` wrapping.

Covers:

- ``enforce()``'s allow path emits ``authz.allow`` at DEBUG; deny path
  emits ``authz.deny`` at INFO and raises ``PolicyDeniedError``.
- ``PolicyDeniedError`` serializes as the structured 403 wire shape through
  the shared ``StructuredApiError`` handler.
- ``_DENIAL_MESSAGE`` covers every ``DenialCode`` member (so a new code
  doesn't crash on first deny).
- ``@requires`` preserves the inventory marker after wrapping, including
  the canonical ``@router.<verb>`` over ``@requires`` decorator order.
- Factory-CRUD registrar routes still carry ``_authz_activity`` after
  the bare-statement → assignment fix.
- An end-to-end allow on a production ``@requires`` route emits exactly
  one ``authz.allow`` record (the wiring canary).
- An unregistered activity propagates ``LookupError`` from ``enforce``,
  rather than being caught and turned into a 403.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import Client, override_settings
from django.urls import path
from ninja import NinjaAPI

from apps.accounts.models import User
from apps.core.authz import enforce
from apps.core.authz.exceptions import (
    _DENIAL_MESSAGE,
    PolicyDeniedError,
    _resolve_message,
)
from apps.core.authz.markers import get_required_activity, requires
from apps.core.authz.route_walker import iter_operations
from apps.core.authz.test_factories import StubPolicyUser
from apps.core.authz.types import Activity, DenialCode, Deny
from apps.core.exceptions import StructuredApiError

# ── Typed capture of authz log records ───────────────────────────────


@dataclass(frozen=True)
class CapturedAuthzLog:
    """A typed snapshot of one ``authz`` log record.

    Documents the fields ``enforce()`` is contractually required to
    emit, so a test asserts against a typed shape rather than poking
    at ``LogRecord.__dict__`` (which spreads ``extra=`` kwargs as
    untyped attributes).
    """

    message: str
    level: int
    user_id: int | None
    activity: str
    code: str | None  # only populated on deny
    target_id: int | None  # None for target-less activities


class _CaptureHandler(logging.Handler):
    """Collects each ``authz`` record into a list of ``CapturedAuthzLog``."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[CapturedAuthzLog] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(
            CapturedAuthzLog(
                message=record.getMessage(),
                level=record.levelno,
                user_id=record.__dict__.get("user_id"),
                activity=record.__dict__["activity"],
                code=record.__dict__.get("code"),
                target_id=record.__dict__.get("target_id"),
            )
        )


@pytest.fixture
def authz_logs() -> Iterator[list[CapturedAuthzLog]]:
    """Capture every record emitted on the ``authz`` logger.

    Yields a list mutated in place; tests append-after-yield is the
    natural shape because the handler records on each ``emit()``.
    """
    handler = _CaptureHandler()
    logger = logging.getLogger("authz")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


# ── Shared exception handler ─────────────────────────────────────────


def _handler(
    request: HttpRequest, exc: StructuredApiError | type[StructuredApiError]
) -> HttpResponse:
    from config.api import _structured_error_response

    assert isinstance(exc, StructuredApiError)
    return _structured_error_response(exc)


# ── Module-level NinjaAPIs and URLconf ───────────────────────────────


_serialization_api = NinjaAPI(urls_namespace="authz_enforcement_serialization_test")


@_serialization_api.get("/deny")
def _deny_view(request: HttpRequest) -> dict[str, str]:
    raise PolicyDeniedError(
        Deny(DenialCode.ACCOUNT_DEACTIVATED, {"hint": "contact support"})
    )


_serialization_api.add_exception_handler(StructuredApiError, _handler)


_integration_api = NinjaAPI(urls_namespace="authz_enforcement_integration_test")


@_integration_api.get("/probe")
@requires(Activity.CATALOG_EDIT)
def _probe(request: HttpRequest) -> dict[str, str]:
    return {"ok": "1"}


_integration_api.add_exception_handler(StructuredApiError, _handler)


urlpatterns = [
    path("serialize/", _serialization_api.urls),
    path("probe/", _integration_api.urls),
]


# ── enforce(): allow + deny paths ────────────────────────────────────


def test_enforce_allow_logs_at_debug(authz_logs: list[CapturedAuthzLog]) -> None:
    enforce(StubPolicyUser(id=42), Activity.CATALOG_EDIT)

    assert authz_logs == [
        CapturedAuthzLog(
            message="authz.allow",
            level=logging.DEBUG,
            user_id=42,
            activity="catalog.edit",
            code=None,
            target_id=None,
        )
    ]


def test_enforce_deny_raises_policy_denied_and_logs_at_info(
    authz_logs: list[CapturedAuthzLog],
) -> None:
    # `WorkOSBackend.get_user` filters `is_active=True`, so a deactivated
    # user 401s on session reload before the gate runs in production.
    # The unit-level test is the right level for the contract.
    with pytest.raises(PolicyDeniedError) as excinfo:
        enforce(StubPolicyUser(is_active=False, id=7), Activity.CATALOG_EDIT)

    assert excinfo.value.decision.code is DenialCode.ACCOUNT_DEACTIVATED
    assert authz_logs == [
        CapturedAuthzLog(
            message="authz.deny",
            level=logging.INFO,
            user_id=7,
            activity="catalog.edit",
            code="account_deactivated",
            target_id=None,
        )
    ]


def test_enforce_logs_target_id_when_target_passed(
    authz_logs: list[CapturedAuthzLog],
) -> None:
    """Target-aware enforce calls must log ``target.id`` so audit
    search can tie a denial back to the affected row.

    Uses ``CATALOG_EDIT`` (target-less in its rule) intentionally —
    this test pins the audit-log contract, not predicate semantics:
    if a caller passes a target on a target-less activity, the id
    should still appear in the log record.
    """

    class _FakeRow:
        id = 4242

    enforce(StubPolicyUser(id=99), Activity.CATALOG_EDIT, target=_FakeRow())

    assert authz_logs == [
        CapturedAuthzLog(
            message="authz.allow",
            level=logging.DEBUG,
            user_id=99,
            activity="catalog.edit",
            code=None,
            target_id=4242,
        )
    ]


# ── _DENIAL_MESSAGE completeness ─────────────────────────────────────


def test_denial_message_covers_every_denial_code() -> None:
    # Cheap insurance: adding a new DenialCode without an entry would
    # KeyError at deny time. Lock the invariant up front.
    assert set(_DENIAL_MESSAGE) == set(DenialCode)


# ── PolicyDeniedError wire-format dispatch ────────────────────────────────


@override_settings(ROOT_URLCONF=__name__)
def test_policy_denied_serializes_as_structured_403() -> None:
    resp = Client().get("/serialize/deny")

    assert resp.status_code == 403
    assert resp["content-type"].startswith("application/json")
    assert resp.json() == {
        "detail": {
            "kind": "policy_denied",
            "message": _resolve_message(Deny(DenialCode.ACCOUNT_DEACTIVATED)),
            "code": "account_deactivated",
            "context": {"hint": "contact support"},
        }
    }


# ── @requires marker preservation + decorator-order contract ─────────


def test_requires_wrapped_callable_carries_marker() -> None:
    @requires(Activity.CATALOG_EDIT)
    def view(request: HttpRequest) -> dict[str, Any]:
        return {}

    assert get_required_activity(view) is Activity.CATALOG_EDIT


def test_router_then_requires_puts_marker_on_view_func() -> None:
    """Locks the canonical `@router.<verb>` over `@requires` ordering.

    Reversing the stack would put the marker on the Ninja-wrapped
    operation, not on the callable the inventory walker reaches via
    ``Operation.view_func``. The walker would then yield an unmarked
    callable and the inventory test would silently lose coverage for
    every route registered that way.
    """
    api = NinjaAPI(urls_namespace="authz_enforcement_decorator_order_test")

    @api.patch("/probe")
    @requires(Activity.CATALOG_EDIT)
    def probe(request: HttpRequest) -> dict[str, str]:
        return {"ok": "1"}

    matches = [
        view
        for method, _path, view in iter_operations(api)
        if get_required_activity(view) is Activity.CATALOG_EDIT and method == "PATCH"
    ]
    assert len(matches) == 1


# ── Factory-CRUD: marker survives the bare-statement → assignment fix ─


def test_factory_crud_routes_carry_marker() -> None:
    """Every factory-registered CRUD route in the project still stamps.

    `requires(...)` is a wrapping decorator that returns a new function,
    so factory call sites must rebind: `_func = requires(...)(_func)`,
    not the bare `requires(...)(_func)` form (which works only for
    in-place-mutation decorators and was the shape during the
    marker-only era before enforcement landed). The factory has four
    such call sites: ``_delete``, ``_restore``, ``_create_parented``,
    and ``_create_unparented``. A silent revert on any one of them
    would drop the gate on every entity using that registrar — the
    create paths in particular are easy to miss because they don't
    share a URL substring with delete/restore. Filter by ``__module__``
    instead so the test is exhaustive across all four shapes.
    """
    from config.api import api

    # The create and delete/restore registrars live in sibling engine modules.
    factory_modules = {
        "apps.catalog.engine.entity_api.create.registrar",
        "apps.catalog.engine.entity_api.delete.registrar",
    }
    mutating_methods = {"POST", "PATCH", "DELETE"}
    factory_routes = [
        (method, path_, view)
        for method, path_, view in iter_operations(api)
        if view.__module__ in factory_modules and method in mutating_methods
    ]

    # Floor reflects the factory's current footprint. Each registered
    # entity contributes 1 delete + 1 restore + 1 create = 3 routes
    # (plus the occasional parented/unparented split). Bump the floor
    # if the catalog grows.
    assert len(factory_routes) >= 4, (
        f"factory-CRUD routes dropped to {len(factory_routes)}; "
        "register_entity_crud / register_entity_create may have regressed."
    )

    # Confirm we're seeing every factory call-site shape — a future
    # refactor that forgets to apply `@requires` to one shape would
    # otherwise pass this test on the strength of the others. The
    # factory names views `<entity>_delete`, `<entity>_restore`, and
    # `<entity>_create[_<suffix>]`; assert each shape contributes at
    # least one route.
    names = [view.__name__ for _, _, view in factory_routes]
    for shape in ("delete", "restore", "create"):
        assert any(f"_{shape}" in name for name in names), (
            f"no factory routes named *_{shape}; saw: {sorted(set(names))}"
        )

    for method, path_, view in factory_routes:
        assert get_required_activity(view) is not None, (
            f"{method} {path_} → {view.__module__}.{view.__qualname__} "
            "lost its @requires marker"
        )


# ── @requires integration: allow then deny via test router ───────────


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_requires_allows_authenticated_active_user(user: User) -> None:
    client = Client()
    client.force_login(user)
    resp = client.get("/probe/probe")
    assert resp.status_code == 200
    assert resp.json() == {"ok": "1"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_requires_denies_with_structured_403_when_check_returns_deny(
    monkeypatch: pytest.MonkeyPatch,
    user: User,
) -> None:
    def _fake_check(
        user: object,
        activity: Activity,
        target: object = None,
        context: object = None,
    ) -> Deny:
        return Deny(DenialCode.ACCOUNT_DEACTIVATED)

    # Patch the symbol the wrapper actually calls — `enforce.py` imported
    # `check` directly, so monkeypatching the evaluator module wouldn't
    # affect the bound name. ``from apps.core.authz import enforce`` and
    # ``apps.core.authz.enforce`` both resolve to the *function* (the
    # package re-exports it, shadowing the submodule), so reach the
    # module via ``sys.modules``.
    import sys

    enforce_module = sys.modules["apps.core.authz.enforce"]
    monkeypatch.setattr(enforce_module, "check", _fake_check)

    client = Client()
    client.force_login(user)
    resp = client.get("/probe/probe")

    assert resp.status_code == 403
    assert resp.json() == {
        "detail": {
            "kind": "policy_denied",
            "message": _resolve_message(Deny(DenialCode.ACCOUNT_DEACTIVATED)),
            "code": "account_deactivated",
            "context": {},
        }
    }


# ── Real-route smoke test (wiring canary) ────────────────────────────


@pytest.mark.django_db
def test_real_route_emits_one_authz_allow_record(
    superuser: User,
    authz_logs: list[CapturedAuthzLog],
) -> None:
    """End-to-end canary on a production `@requires` route.

    A test-only router can mask Ninja-internal regressions in
    `Operation.view_func` resolution, `functools.wraps` signature
    introspection, and decorator-order sensitivity. The synthetic tests
    above cover wrapper logic; this one covers wiring.

    Picks `kiosk.edit` as the cheapest production target — the body
    only runs `_require_superuser` and a model insert; no fixtures or
    catalog plumbing required.
    """
    client = Client()
    client.force_login(superuser)

    resp = client.post("/api/kiosk/configs/")

    assert resp.status_code == 201

    allow_records = [r for r in authz_logs if r.message == "authz.allow"]
    assert len(allow_records) == 1
    assert allow_records[0].activity == "kiosk.edit"
    assert allow_records[0].user_id == superuser.pk


# ── Verification gate: end-to-end through a real route ──────────────


@pytest.mark.django_db
def test_unverified_user_gets_structured_403_with_verification_required(
    authz_logs: list[CapturedAuthzLog],
) -> None:
    """End-to-end: an active, authenticated, unverified user mutating a real
    route gets a 403 whose body is the canonical policy_denied envelope with
    code=verification_required.

    The unit-level registry-completeness test proves `check()` denies; this
    proves the wire body actually carries the expected structure through
    Ninja, the exception handler, and the schema serializer.

    Doubles as the no-superuser-bypass invariant: the user is is_superuser=
    True, and the gate still denies. Anyone adding `if user.is_superuser:
    return Allow()` to a predicate or the evaluator will fail this test.
    The is_superuser flag is also what gets us past kiosk's inline
    `_require_superuser` check so the policy gate is the only thing left
    to fire.
    """
    from apps.accounts.test_factories import make_user

    unverified = make_user(is_staff=True, is_superuser=True, email_verified=False)
    client = Client()
    client.force_login(unverified)

    resp = client.post("/api/kiosk/configs/")

    assert resp.status_code == 403
    assert resp.json() == {
        "detail": {
            "kind": "policy_denied",
            "message": _resolve_message(Deny(DenialCode.VERIFICATION_REQUIRED)),
            "code": "verification_required",
            "context": {},
        }
    }
    deny_records = [r for r in authz_logs if r.message == "authz.deny"]
    assert len(deny_records) == 1
    assert deny_records[0].activity == "kiosk.edit"
    assert deny_records[0].code == "verification_required"


# ── LookupError contract ─────────────────────────────────────────────


class _BogusActivity:
    """Stand-in for an unregistered Activity-like value.

    `Activity` is a closed StrEnum; the registry dict keys off the enum
    member, and any non-registered key triggers the LookupError branch
    in the evaluator. A sentinel avoids polluting `Activity.__members__`.
    """

    value = "bogus.activity"


def test_unregistered_activity_raises_lookup_error() -> None:
    """`LookupError` must propagate, not be caught and turned into a 403.

    The registry-completeness test keeps this branch dead in normal
    operation; this test pins the contract that misconfiguration
    surfaces as a 500-class failure (unhandled exception), not a
    misleading 403. Hitting `enforce` directly is what every caller
    of the policy actually observes.
    """
    user = StubPolicyUser()
    with pytest.raises(LookupError, match="No rule registered"):
        enforce(user, _BogusActivity())  # type: ignore[arg-type]
