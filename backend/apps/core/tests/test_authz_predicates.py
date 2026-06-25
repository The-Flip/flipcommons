"""Unit tests for the built-in predicates.

Confirms `is_authenticated`, `is_active`, and `email_verified` produce
the right Decision for both authenticated `User` and `AnonymousUser`,
and that both classes satisfy the attribute surface `PolicyUser`
declares.
"""

from __future__ import annotations

from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from apps.accounts.test_factories import make_user
from apps.core.authz.predicates import (
    email_verified,
    is_active,
    is_authenticated,
    is_staff,
    is_superuser,
)
from apps.core.authz.types import Allow, DenialCode, Deny, PolicyUser

# PolicyUser uses @property declarations, so its attributes don't appear
# in __annotations__; hardcode them here for the protocol-fit checks.
_POLICY_USER_ATTRS = (
    "id",
    "actor_id",
    "is_authenticated",
    "is_active",
    "email_verified",
    "is_staff",
    "is_superuser",
)


def _anon() -> PolicyUser:
    """AnonymousUser as PolicyUser.

    The `email_verified` attribute is set at runtime by
    ``accounts.apps.AccountsConfig.ready()`` and is not visible to
    django-stubs, so the cast bridges the runtime patch to the static
    Protocol surface.
    """
    return cast(PolicyUser, AnonymousUser())


def test_anonymous_user_denied_by_is_authenticated():
    decision = is_authenticated(_anon(), None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.AUTH_REQUIRED


def test_anonymous_user_denied_by_is_active():
    """AnonymousUser.is_active is False, so is_active denies with ACCOUNT_DEACTIVATED.

    The "deactivated" framing is wrong for an anonymous user, but
    priority ordering in `check()` will surface AUTH_REQUIRED instead —
    see test_authz_evaluator. This test only locks the predicate's
    contract.
    """
    decision = is_active(_anon(), None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.ACCOUNT_DEACTIVATED


def test_anonymous_user_denied_by_email_verified():
    """AnonymousUser.email_verified is False (set in apps.ready())."""
    decision = email_verified(_anon(), None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.VERIFICATION_REQUIRED


def test_anonymous_user_email_verified_attr_is_false():
    """Pin the apps.ready() monkey-patch contract directly.

    A missing patch would otherwise surface as an AttributeError in
    some downstream predicate test rather than a clear failure here.
    """
    assert AnonymousUser().email_verified is False  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_authenticated_active_verified_user_passes_all():
    user = make_user(email="alice@example.com", password="x", email_verified=True)
    assert isinstance(is_authenticated(user, None, None), Allow)
    assert isinstance(is_active(user, None, None), Allow)
    assert isinstance(email_verified(user, None, None), Allow)


@pytest.mark.django_db
def test_inactive_user_denied_by_is_active():
    user = make_user(email="dormant@example.com", password="x", is_active=False)
    decision = is_active(user, None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.ACCOUNT_DEACTIVATED


@pytest.mark.django_db
def test_unverified_user_denied_by_email_verified():
    user = make_user(email="unverified@example.com", password="x", email_verified=False)
    decision = email_verified(user, None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.VERIFICATION_REQUIRED


def test_anonymous_user_denied_by_is_staff():
    decision = is_staff(_anon(), None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.ROLE_REQUIRED
    assert decision.context == {"required_role": "staff"}


def test_anonymous_user_denied_by_is_superuser():
    decision = is_superuser(_anon(), None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.ROLE_REQUIRED
    assert decision.context == {"required_role": "superuser"}


@pytest.mark.django_db
def test_non_staff_user_denied_by_is_staff():
    user = make_user(email="regular@example.com", password="x")
    decision = is_staff(user, None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.ROLE_REQUIRED
    assert decision.context == {"required_role": "staff"}


@pytest.mark.django_db
def test_staff_user_passes_is_staff():
    user = make_user(email="staff@example.com", password="x", is_staff=True)
    assert isinstance(is_staff(user, None, None), Allow)


@pytest.mark.django_db
def test_non_superuser_user_denied_by_is_superuser():
    user = make_user(email="staffonly@example.com", password="x", is_staff=True)
    decision = is_superuser(user, None, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.ROLE_REQUIRED
    assert decision.context == {"required_role": "superuser"}


@pytest.mark.django_db
def test_superuser_passes_is_superuser():
    user = make_user(
        email="root@example.com", password="x", is_staff=True, is_superuser=True
    )
    assert isinstance(is_superuser(user, None, None), Allow)


@pytest.mark.django_db
def test_is_staff_and_is_superuser_are_independent():
    """Pin the predicate contract: `is_superuser=True` does not grant `is_staff`.

    Django's `createsuperuser` happens to set both flags, but the policy
    treats them as independent attributes — a future refactor that makes
    `is_superuser` short-circuit `is_staff` should fail loudly here.
    """
    user_model = get_user_model()
    superuser_only = user_model(
        email="su-only@example.com", is_staff=False, is_superuser=True
    )
    staff_only = user_model(
        email="staff-only@example.com", is_staff=True, is_superuser=False
    )
    assert isinstance(is_staff(superuser_only, None, None), Deny)
    assert isinstance(is_superuser(superuser_only, None, None), Allow)
    assert isinstance(is_staff(staff_only, None, None), Allow)
    assert isinstance(is_superuser(staff_only, None, None), Deny)


def test_anonymous_user_satisfies_policy_user_protocol():
    user = AnonymousUser()
    for attr in _POLICY_USER_ATTRS:
        assert hasattr(user, attr), f"AnonymousUser missing {attr!r}"


@pytest.mark.django_db
def test_real_user_satisfies_policy_user_protocol():
    user = make_user(email="bob@example.com", password="x")
    for attr in _POLICY_USER_ATTRS:
        assert hasattr(user, attr), f"User missing {attr!r}"
