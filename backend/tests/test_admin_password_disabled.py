"""Tests for the WorkOS-only admin login policy.

The Django admin password form is the only brute-forceable login surface
on the backend, so it's replaced by a redirect to the WorkOS-backed
``/api/auth/login/`` endpoint (see ``apps.core.admin_site.FlipAdminSite``).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from django.http.response import HttpResponseBase
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.test_factories import make_user

# Only the tests that actually *render* the admin index template need
# StaticFilesStorage (the default ManifestStaticFilesStorage requires a
# collectstatic-built manifest, which tests don't produce). All other tests
# in this file return 302/404 without rendering and need no override.
_STATICFILES_OVERRIDE = override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)


def _assert_redirects_to_workos(response: HttpResponseBase, expected_next: str) -> None:
    assert response.status_code == 302
    parts = urlsplit(response["Location"])
    assert parts.path == "/api/auth/login/"
    assert parse_qs(parts.query).get("next") == [expected_next]


def test_get_redirects_unauthenticated_visitor_to_workos():
    response = Client().get("/djadmin/login/")
    _assert_redirects_to_workos(response, "/djadmin/")


def test_get_preserves_admin_next_param():
    """``admin_view`` appends ?next=<original_url>; forward it to WorkOS."""
    response = Client().get("/djadmin/login/?next=/djadmin/accounts/user/")
    _assert_redirects_to_workos(response, "/djadmin/accounts/user/")


def test_get_rejects_open_redirect_via_next():
    """An off-host ?next= must not leak through to WorkOS."""
    response = Client().get("/djadmin/login/?next=https://evil.example.com/")
    _assert_redirects_to_workos(response, "/djadmin/")


def test_get_rejects_same_host_non_admin_next():
    """Same-host but non-admin ?next= is also clamped to the admin root.

    The override's contract is "log into admin," so a ``next=`` pointing at
    a non-admin path is either a stray pass-through or abuse of the
    endpoint as a generic post-WorkOS redirector.
    """
    response = Client().get("/djadmin/login/?next=/some-app-page/")
    _assert_redirects_to_workos(response, "/djadmin/")


def test_post_credentials_redirects_without_authenticating():
    """No password form exists; POSTing credentials just drops the body and redirects."""
    response = Client().post("/djadmin/login/", {"username": "x", "password": "y"})
    _assert_redirects_to_workos(response, "/djadmin/")


@pytest.mark.django_db
def test_authenticated_non_staff_gets_404_not_redirect_loop():
    """If they were already logged in but admin rejected them, they lack ``is_staff``.

    Bouncing them through WorkOS would loop, so the login URL 404s instead.
    """
    user = make_user(is_staff=False)
    client = Client()
    client.force_login(user)
    assert client.get("/djadmin/login/").status_code == 404


@pytest.mark.django_db
def test_authenticated_staff_redirected_to_admin_index(superuser: User):
    """Matches stock ``AdminSite.login``: an already-permitted caller is bounced to the index."""
    client = Client()
    client.force_login(superuser)
    response = client.get("/djadmin/login/")
    assert response.status_code == 302
    assert response["Location"] == "/djadmin/"


@pytest.mark.django_db
def test_password_change_form_is_404_for_staff(superuser: User):
    """Django passwords are inert — WorkOS owns auth — so the change form must not be reachable.

    Guards against an operator setting a password that could silently become
    an auth surface if a future feature reintroduces ``authenticate(username,
    password)`` (DRF basic auth, an emergency escape hatch, etc.).
    """
    client = Client()
    client.force_login(superuser)
    assert client.get("/djadmin/password_change/").status_code == 404
    assert client.get("/djadmin/password_change/done/").status_code == 404


@pytest.mark.django_db
@_STATICFILES_OVERRIDE
def test_staff_can_still_reach_admin(superuser: User):
    """Regression guard: overriding ``login`` must not break the rest of admin."""
    client = Client()
    client.force_login(superuser)
    assert client.get("/djadmin/").status_code == 200


def test_workos_login_path_matches_admin_redirect_target():
    """Pin the hardcoded path in ``admin_site.py`` to the route's reverse.

    The admin override hardcodes ``/api/auth/login/`` (the comment there
    explains why we don't ``reverse()`` at import time). If someone renames
    the route, this assertion catches the silent breakage instead of
    waiting for admin login to 404 in production.
    """
    assert reverse("api:workos_login") == "/api/auth/login/"
