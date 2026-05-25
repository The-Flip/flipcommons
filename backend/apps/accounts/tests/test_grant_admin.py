"""Tests for the ``grant_admin`` management command."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.test_factories import make_user


@pytest.mark.django_db
def test_promotes_regular_user():
    user = make_user(email="alice@example.com", workos_user_id="user_alice")
    assert not user.is_staff
    assert not user.is_superuser

    out = StringIO()
    call_command("grant_admin", "alice@example.com", stdout=out)

    user.refresh_from_db()
    assert user.is_staff
    assert user.is_superuser
    assert "Promoted alice@example.com" in out.getvalue()


@pytest.mark.django_db
def test_email_match_is_case_insensitive():
    """Mirrors ``workos_match.py``'s ``email__iexact`` lookup."""
    make_user(email="alice@example.com", workos_user_id="user_alice")

    call_command("grant_admin", "ALICE@Example.COM", stdout=StringIO())

    assert User.objects.get(email="alice@example.com").is_superuser


@pytest.mark.django_db
def test_idempotent_when_already_admin():
    make_user(
        email="alice@example.com",
        workos_user_id="user_alice",
        is_staff=True,
        is_superuser=True,
    )

    out = StringIO()
    call_command("grant_admin", "alice@example.com", stdout=out)

    assert "already an admin" in out.getvalue()


@pytest.mark.django_db
def test_promotes_staff_to_superuser():
    """A staff-only user gets superuser added, not re-set from scratch."""
    user = make_user(
        email="alice@example.com",
        workos_user_id="user_alice",
        is_staff=True,
    )

    out = StringIO()
    call_command("grant_admin", "alice@example.com", stdout=out)

    user.refresh_from_db()
    assert user.is_superuser
    assert "Promoted alice@example.com: set is_superuser." in out.getvalue()


@pytest.mark.django_db
def test_unknown_email_raises_command_error():
    with pytest.raises(CommandError, match="No user found"):
        call_command("grant_admin", "nobody@example.com", stdout=StringIO())


@pytest.mark.django_db
def test_refuses_user_without_workos_link():
    """A ``createsuperuser``d row has no workos_user_id and cannot sign in."""
    make_user(email="alice@example.com", workos_user_id=None)

    with pytest.raises(CommandError, match="no WorkOS link"):
        call_command("grant_admin", "alice@example.com", stdout=StringIO())

    user = User.objects.get(email="alice@example.com")
    assert not user.is_staff
    assert not user.is_superuser


@pytest.mark.django_db
def test_refuses_deactivated_user():
    """A soft-deleted/disabled account cannot sign in; granting admin is meaningless."""
    make_user(
        email="alice@example.com",
        workos_user_id="user_alice",
        is_active=False,
    )

    with pytest.raises(CommandError, match="deactivated"):
        call_command("grant_admin", "alice@example.com", stdout=StringIO())

    user = User.objects.get(email="alice@example.com")
    assert not user.is_staff
    assert not user.is_superuser
