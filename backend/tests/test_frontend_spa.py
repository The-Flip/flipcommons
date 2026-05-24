"""Tests for Django routing when SvelteKit owns frontend routes."""

import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_api_health_not_intercepted():
    """GET /api/health should reach Django Ninja, not the catch-all."""
    client = Client()
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
def test_admin_login_not_intercepted():
    """GET /djadmin/login/ should reach Django Admin, not the catch-all."""
    client = Client()
    response = client.get("/djadmin/login/")
    assert response.status_code == 200


def test_api_no_trailing_slash_not_intercepted():
    """GET /api should not be caught by the SPA catch-all."""
    client = Client()
    response = client.get("/api")
    # Django's APPEND_SLASH redirects /api → /api/ since the catch-all
    # regex excludes both /api and /api/...
    assert response.status_code in (301, 302)
    assert response["Location"].endswith("/api/")


def test_admin_no_trailing_slash_not_intercepted():
    """GET /djadmin should not be caught by the SPA catch-all."""
    client = Client()
    response = client.get("/djadmin")
    assert response.status_code in (200, 301, 302)


@override_settings(DEBUG=True)
def test_frontend_route_not_served_by_django():
    """Frontend routes are handled by SvelteKit/Proxy, not Django."""
    client = Client()
    response = client.get("/titles/medieval-madness")
    assert response.status_code == 404
