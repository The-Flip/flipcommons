from typing import Any
from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.http import url_has_allowed_host_and_scheme

# WorkOS login lives on the django-ninja router at /api/auth/; importing the
# api module here to reverse() it would create a circular import on admin load.
# The path is stable and wired in config/urls.py + apps/accounts/api/__init__.py.
_WORKOS_LOGIN_PATH = "/api/auth/login/"
_ADMIN_ROOT = "/djadmin/"


class FlipAdminSite(admin.AdminSite):
    """Admin site that disables every Django-password surface.

    Staff authenticate through WorkOS via the main app; Django's ``User.password``
    field is inert (no live code consumes it). Three overrides close the surfaces
    the stock site exposes:

    * ``login`` — redirects to WorkOS instead of rendering the password form
      (the only brute-forceable login surface on the backend).
    * ``password_change`` / ``password_change_done`` — 404. Lets nobody set a
      password that could silently become an auth surface if a future feature
      reintroduces ``authenticate(username=..., password=...)`` (DRF basic
      auth, an emergency escape hatch, etc.).

    Overriding the methods (instead of only the URL patterns) means any caller
    that does ``super().<method>(...)`` from a future subclass is covered by
    the same policy, and the URLs stay reverse-resolvable so admin templates
    that reference them by name don't ``NoReverseMatch``.
    """

    def login(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        # Already-authenticated callers split two ways: staff users who
        # bookmarked or typed /djadmin/login/ get the stock "you're already
        # in" redirect to the index; non-staff users get 404 (bouncing them
        # through WorkOS would loop — WorkOS silently re-issues the same
        # session, admin rejects them again).
        if request.user.is_authenticated:
            if request.user.is_staff:
                return HttpResponseRedirect(_ADMIN_ROOT)
            raise Http404

        # ``next_url`` is what the user lands on post-WorkOS. Confine it to
        # admin paths: this endpoint's contract is "log into admin," so any
        # non-admin destination is either Django passing through a stray
        # redirect or a caller abusing the override as a generic redirector.
        # ``url_has_allowed_host_and_scheme`` only gates host/scheme.
        next_url = request.GET.get(REDIRECT_FIELD_NAME, _ADMIN_ROOT)
        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts=set()
        ) or not next_url.startswith(_ADMIN_ROOT):
            next_url = _ADMIN_ROOT

        target = f"{_WORKOS_LOGIN_PATH}?{urlencode({REDIRECT_FIELD_NAME: next_url})}"
        return HttpResponseRedirect(target)

    # Return type matches the supertype (which is never actually returned —
    # both bodies raise — but mypy enforces signature compatibility).
    def password_change(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> TemplateResponse:
        raise Http404

    def password_change_done(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> TemplateResponse:
        raise Http404
