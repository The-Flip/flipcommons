from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from apps.accounts.models import User
from apps.accounts.test_factories import make_user
from apps.catalog.models import CreditRole, Person
from apps.provenance.models import Source

if TYPE_CHECKING:
    from sentry_sdk._types import Event


@pytest.fixture
def user(db: None) -> User:
    """Default test user.

    Project-root fixture so individual test files don't need their own
    ``def user(db): ...``. A local fixture with the same name shadows
    this one (e.g. ``test_rate_limits.py`` does so to add a teardown).
    Tests that need overrides or multiple users should call ``make_user``
    directly from ``apps.accounts.test_factories``.
    """
    return make_user()


@pytest.fixture
def staff(db: None) -> User:
    """Default staff test user."""
    return make_user(is_staff=True)


@pytest.fixture
def superuser(db: None) -> User:
    """Default superuser test user (also staff)."""
    return make_user(is_staff=True, is_superuser=True)


@pytest.fixture
def bootstrap_source(db: None) -> Source:
    """Low-priority editorial Source for seeding baseline name/scalar claims.

    Priority 1 ensures bootstrap claims never outrank real source or user
    claims in tests that set up competing claims. Project-root fixture so test
    files don't each define their own; a local fixture of the same name shadows
    it (and tests needing a different priority/slug should call
    ``Source.objects.create`` directly).
    """
    return Source.objects.create(
        name="Bootstrap", slug="bootstrap", source_type="editorial", priority=1
    )


@pytest.fixture
def credit_targets(db):
    """Seed Person + CreditRole rows commonly referenced by credit claim tests.

    Relationship claim validation checks target existence at the claim
    boundary, so any test that creates credit claims needs the referenced
    Person and CreditRole rows to exist.

    Returns a dict keyed by slug for convenient ``.pk`` access in tests.
    """
    Person.objects.bulk_create(
        [
            Person(name="Pat Lawlor", slug="pat-lawlor"),
            Person(name="John Youssi", slug="john-youssi"),
        ],
        update_conflicts=True,
        unique_fields=["slug"],
        update_fields=["name"],
    )
    CreditRole.objects.bulk_create(
        [
            CreditRole(name="Design", slug="design"),
            CreditRole(name="Art", slug="art"),
        ],
        update_conflicts=True,
        unique_fields=["slug"],
        update_fields=["name"],
    )
    # Re-fetch to guarantee PKs are populated (bulk_create with
    # update_conflicts may not set pk on all backends).
    persons = {
        p.slug: p for p in Person.objects.filter(slug__in=["pat-lawlor", "john-youssi"])
    }
    roles = {r.slug: r for r in CreditRole.objects.filter(slug__in=["design", "art"])}
    return {"persons": persons, "roles": roles}


@pytest.fixture(autouse=True)
def _use_locmem_cache(settings):
    """Use in-memory cache for tests instead of file-based cache.

    File-based cache persists across test boundaries and causes flaky
    failures when other tests call invalidate_response_cache() during their execution.

    LocMemCache instances created with the default ``LOCATION`` share the
    same process-level storage dict, so even though ``settings.CACHES`` is
    re-applied per test, leftover entries (especially rate-limit buckets
    keyed by reused user PKs) persist across tests. Clear explicitly.
    """
    from django.core.cache import cache

    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# Sentry test helpers
# ---------------------------------------------------------------------------
# Sentry's scope is process-global and survives SDK re-init, so any test
# that touches the SDK has to reset state at the boundary or earlier tests
# leak. These fixtures centralize the init / cleanup dance so individual
# test files don't reinvent it.


class SentryRecordingTransport(Transport):
    """In-memory transport for tests asserting "what got captured."

    Pair with the ``sentry_recording`` fixture below to verify event
    payloads without exercising the real HTTPS transport.
    """

    def __init__(self) -> None:
        super().__init__()
        self.events: list[Event] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            event = item.payload.json
            if event is not None:
                self.events.append(event)


def _reset_sentry_scope_state() -> None:
    """Clear process-global Sentry scope state (user + tags + everything).

    ``set_user`` / ``set_tag`` writes survive SDK re-init because they
    live on the isolation scope, not the client. Without this reset,
    state set by one test would leak into the next test's
    ``isolation_scope()`` (which forks from the parent). ``clear()``
    wipes user, tags, contexts, breadcrumbs, extras, and fingerprint
    — exactly the right granularity.
    """
    sentry_sdk.get_global_scope().clear()
    sentry_sdk.get_isolation_scope().clear()


@pytest.fixture
def sentry_active() -> Iterator[None]:
    """Boot Sentry with an active (no-op) client for the test.

    Use when code-under-test gates on ``get_client().is_active()`` and
    needs that to return True. Scope state is cleared on both setup
    and teardown so tests don't bleed into each other.
    """
    _reset_sentry_scope_state()
    sentry_sdk.init(dsn="https://public@example.test/1")
    try:
        yield
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.Scope.get_global_scope().set_client(None)
        _reset_sentry_scope_state()


@pytest.fixture
def sentry_recording() -> Iterator[SentryRecordingTransport]:
    """Boot Sentry with a ``SentryRecordingTransport`` for the test.

    Captures every envelope the SDK would have sent; assert on
    ``transport.events`` to verify the captured shape.
    """
    _reset_sentry_scope_state()
    transport = SentryRecordingTransport()
    sentry_sdk.init(dsn="https://public@example.test/1", transport=transport)
    try:
        yield transport
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.Scope.get_global_scope().set_client(None)
        _reset_sentry_scope_state()


@pytest.fixture(autouse=True)
def _default_display_policy_show_all(settings):
    """Default Constance display policy to show-all for tests.

    Most tests don't care about license filtering. Tests that specifically
    test threshold behavior can override via settings fixture.
    """
    from constance.test import override_config

    with override_config(CONTENT_DISPLAY_POLICY="show-all"):
        yield
