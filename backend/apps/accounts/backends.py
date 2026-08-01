"""Authentication backend for users authenticated via WorkOS AuthKit.

This backend does not implement authenticate() because the actual
authentication happens via the WorkOS SDK in the callback view.
It only implements get_user() so Django's session framework can
reload the user from the session.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.http import HttpRequest

from apps.core.types import UserId

User = get_user_model()


class WorkOSBackend:
    def authenticate(
        self,
        request: HttpRequest | None,
        **credentials: Any,  # noqa: ANN401 - Django auth backends receive framework-defined credentials.
    ) -> None:
        return None

    def get_user(self, user_id: UserId) -> AbstractBaseUser | None:
        # is_active filter: a disabled user stops being authenticated on the
        # very next request via AuthenticationMiddleware, no session flush
        # needed.
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None
