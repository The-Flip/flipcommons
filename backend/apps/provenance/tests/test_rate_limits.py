"""Tests for per-user rolling-window rate limits."""

from __future__ import annotations

import time
from unittest import mock

import pytest
from django.core.cache import cache

from apps.accounts.test_factories import make_user
from apps.core.authz.markers import get_required_activity, requires
from apps.core.authz.types import Activity
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    DELETE_RATE_LIMIT_SPEC,
    EDIT_RATE_LIMIT_SPEC,
    RateLimitExceededError,
    RateLimitSpec,
    check_and_record,
    get_rate_limit_exempt_reason,
    get_rate_limit_spec,
    rate_limit_exempt,
    rate_limited,
    reset_for_user,
)

SPEC = RateLimitSpec(bucket="test", limit=3, window_seconds=60)


@pytest.fixture
def user(db):
    u = make_user()
    yield u
    reset_for_user(u, SPEC.bucket)


@pytest.fixture
def staff_user(db):
    u = make_user(is_staff=True)
    yield u
    reset_for_user(u, SPEC.bucket)


@pytest.fixture(autouse=True)
def _flush_cache():
    cache.clear()
    yield
    cache.clear()


class TestRateLimits:
    def test_under_limit_passes(self, user):
        for _ in range(SPEC.limit):
            check_and_record(user, SPEC)

    def test_over_limit_raises(self, user):
        for _ in range(SPEC.limit):
            check_and_record(user, SPEC)
        with pytest.raises(RateLimitExceededError) as exc:
            check_and_record(user, SPEC)
        assert exc.value.retry_after >= 1
        assert exc.value.bucket == "test"

    def test_retry_after_does_not_drift_on_repeated_rejection(self, user):
        """The spec forbids 429 responses extending the lockout horizon."""
        base = 1_000_000.0
        with mock.patch("apps.provenance.rate_limits.time.time") as fake_time:
            fake_time.return_value = base
            for _ in range(SPEC.limit):
                check_and_record(user, SPEC)

            fake_time.return_value = base + 5
            with pytest.raises(RateLimitExceededError) as first:
                check_and_record(user, SPEC)

            # 20 more blocked retries spaced 1s apart.
            last = first
            for i in range(1, 21):
                fake_time.return_value = base + 5 + i
                with pytest.raises(RateLimitExceededError) as exc:
                    check_and_record(user, SPEC)
                last = exc

        # Horizon anchored to the oldest admitted attempt, not the last retry.
        assert first.value.retry_after >= last.value.retry_after

    def test_validation_reject_still_counts(self, user):
        """Endpoints call check_and_record before validation, so every
        attempt — including those that go on to fail — consumes a slot."""
        for _ in range(SPEC.limit):
            check_and_record(user, SPEC)
        with pytest.raises(RateLimitExceededError):
            check_and_record(user, SPEC)

    def test_window_expiry(self, user):
        base = 1_000_000.0
        with mock.patch("apps.provenance.rate_limits.time.time") as fake_time:
            fake_time.return_value = base
            for _ in range(SPEC.limit):
                check_and_record(user, SPEC)
            fake_time.return_value = base + SPEC.window_seconds + 1
            # After the window has elapsed, the bucket is empty again.
            check_and_record(user, SPEC)

    def test_staff_bypass(self, staff_user):
        for _ in range(SPEC.limit * 10):
            check_and_record(staff_user, SPEC)

    def test_buckets_are_independent(self, user):
        other_spec = RateLimitSpec(
            bucket="other", limit=SPEC.limit, window_seconds=SPEC.window_seconds
        )
        for _ in range(SPEC.limit):
            check_and_record(user, SPEC)
        # Different bucket for the same user is untouched.
        for _ in range(SPEC.limit):
            check_and_record(user, other_spec)
        with pytest.raises(RateLimitExceededError):
            check_and_record(user, SPEC)

    def test_users_are_independent(self, user, db):
        other = make_user()
        try:
            for _ in range(SPEC.limit):
                check_and_record(user, SPEC)
            for _ in range(SPEC.limit):
                check_and_record(other, SPEC)
            with pytest.raises(RateLimitExceededError):
                check_and_record(user, SPEC)
        finally:
            reset_for_user(other, SPEC.bucket)

    def test_anonymous_raises(self):
        from django.contrib.auth.models import AnonymousUser

        with pytest.raises(RateLimitExceededError):
            check_and_record(AnonymousUser(), SPEC)


class TestBucketConfig:
    """Pin the configured bucket parameters so accidental edits in
    constants.py are caught at test time rather than in production."""

    def test_delete_bucket_is_5_per_day(self):
        assert DELETE_RATE_LIMIT_SPEC.bucket == "delete"
        assert DELETE_RATE_LIMIT_SPEC.limit == 5
        assert DELETE_RATE_LIMIT_SPEC.window_seconds == 86_400

    def test_create_and_delete_buckets_are_independent(self, user):
        for _ in range(CREATE_RATE_LIMIT_SPEC.limit):
            check_and_record(user, CREATE_RATE_LIMIT_SPEC)
        # Filling the create bucket does not consume delete slots.
        for _ in range(DELETE_RATE_LIMIT_SPEC.limit):
            check_and_record(user, DELETE_RATE_LIMIT_SPEC)
        reset_for_user(user, CREATE_RATE_LIMIT_SPEC.bucket)
        reset_for_user(user, DELETE_RATE_LIMIT_SPEC.bucket)


class TestEditBucketConfig:
    def test_edit_bucket_is_60_per_hour(self):
        assert EDIT_RATE_LIMIT_SPEC.bucket == "edit"
        assert EDIT_RATE_LIMIT_SPEC.limit == 60
        assert EDIT_RATE_LIMIT_SPEC.window_seconds == 3_600

    def test_edit_bucket_is_independent_of_create_and_delete(self, user):
        for _ in range(CREATE_RATE_LIMIT_SPEC.limit):
            check_and_record(user, CREATE_RATE_LIMIT_SPEC)
        for _ in range(DELETE_RATE_LIMIT_SPEC.limit):
            check_and_record(user, DELETE_RATE_LIMIT_SPEC)
        # Filling create + delete leaves edit fully available.
        check_and_record(user, EDIT_RATE_LIMIT_SPEC)
        reset_for_user(user, CREATE_RATE_LIMIT_SPEC.bucket)
        reset_for_user(user, DELETE_RATE_LIMIT_SPEC.bucket)
        reset_for_user(user, EDIT_RATE_LIMIT_SPEC.bucket)


class _Req:
    """Minimal request stand-in carrying ``.user`` only."""

    def __init__(self, user):
        self.user = user


class TestRateLimitedDecorator:
    """Unit tests for the @rate_limited decorator itself."""

    def test_charges_the_bucket_per_request(self, user):
        spec = RateLimitSpec(bucket="dec_charge", limit=2, window_seconds=60)

        @rate_limited(spec)
        def view(request):
            return "ok"

        try:
            assert view(_Req(user)) == "ok"
            assert view(_Req(user)) == "ok"
            with pytest.raises(RateLimitExceededError) as exc:
                view(_Req(user))
            assert exc.value.bucket == "dec_charge"
        finally:
            reset_for_user(user, spec.bucket)

    def test_stamps_marker_readable_via_accessor(self):
        spec = RateLimitSpec(bucket="dec_stamp", limit=1, window_seconds=60)

        @rate_limited(spec)
        def view(request):
            return None

        assert get_rate_limit_spec(view) is spec

    def test_stacking_with_requires_propagates_both_markers(self):
        """Pin the `update_wrapper.__dict__` propagation the inventory
        walker relies on. If a future refactor of ``@requires`` drops
        ``WRAPPER_UPDATES`` (the ``__dict__`` copy), the outer marker
        would silently disappear and only this test would catch it."""
        spec = RateLimitSpec(bucket="dec_stack", limit=1, window_seconds=60)

        @requires(Activity.CATALOG_EDIT)
        @rate_limited(spec)
        def view_a(request):
            return None

        @rate_limited(spec)
        @requires(Activity.CATALOG_EDIT)
        def view_b(request):
            return None

        # Both orders: the outermost callable carries BOTH markers.
        for view in (view_a, view_b):
            assert get_required_activity(view) == Activity.CATALOG_EDIT
            assert get_rate_limit_spec(view) is spec


class TestRateLimitExemptDecorator:
    def test_stamps_reason_readable_via_accessor(self):
        @rate_limit_exempt("undo inverts an existing changeset")
        def view(request):
            return None

        assert get_rate_limit_exempt_reason(view) == (
            "undo inverts an existing changeset"
        )

    def test_stacking_with_requires_propagates_both_markers(self):
        """Unlike ``@rate_limited``, ``@rate_limit_exempt`` doesn't wrap —
        it just ``setattr``s on the original function. When stacked under
        ``@requires`` (which rebuilds the function via ``FunctionType``),
        the exempt marker must still reach the outermost callable via
        ``update_wrapper``'s ``__dict__`` copy. Pin that, so the first
        caller doesn't trip a silent regression."""

        @requires(Activity.CATALOG_EDIT)
        @rate_limit_exempt("test")
        def view(request):
            return None

        assert get_required_activity(view) == Activity.CATALOG_EDIT
        assert get_rate_limit_exempt_reason(view) == "test"

    def test_empty_reason_rejected_at_decoration_time(self):
        with pytest.raises(ValueError, match="non-empty reason"):

            @rate_limit_exempt("")
            def view_a(request):
                return None

        with pytest.raises(ValueError, match="non-empty reason"):

            @rate_limit_exempt("   ")
            def view_b(request):
                return None


# Silence time.sleep warnings in case any test uses real time.
_ = time
