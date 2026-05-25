"""Promote an existing user to Django admin (is_staff + is_superuser).

Bootstrap path for the WorkOS-only login policy (see
``apps.core.admin_site.FlipAdminSite``): sign up via WorkOS as a regular
user, then run ``manage.py grant_admin <email>`` to grant admin access.
The admin password form is disabled, so the legacy
``manage.py createsuperuser`` flow produces a row that can never sign in.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User

# Privilege grants are security-significant audit events. Logged at WARNING so
# they surface in default-level log views and incident-response queries
# ("who got staff and when?") without grepping operator shell scrollback.
log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Grant Django admin access (is_staff + is_superuser) to an existing user."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "email",
            help="Email of the user to promote (case-insensitive).",
        )

    def handle(
        self,
        *args: object,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        email = options["email"]
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist as exc:
            raise CommandError(
                f"No user found with email {email!r}. "
                "Sign up via WorkOS first, then re-run this command."
            ) from exc

        # Refuse to grant admin to rows that can't actually sign in. The two
        # ways to reach these states are both operator errors: a stray
        # `createsuperuser` (leaves workos_user_id NULL) or a mid-soft-delete
        # row (the user.deleted webhook clears workos_user_id and flips
        # is_active off — see models.py). Granting admin in either case
        # silently produces an admin row that can never sign in.
        if user.workos_user_id is None:
            raise CommandError(
                f"{user.email} has no WorkOS link and cannot sign in. "
                "Sign in via WorkOS first to populate workos_user_id, then re-run."
            )
        if not user.is_active:
            raise CommandError(
                f"{user.email} is deactivated. Reactivate the account first."
            )

        changed: list[str] = []
        if not user.is_staff:
            user.is_staff = True
            changed.append("is_staff")
        if not user.is_superuser:
            user.is_superuser = True
            changed.append("is_superuser")

        if not changed:
            self.stdout.write(f"{user.email} is already an admin — no changes.")
            return

        user.save(update_fields=changed)
        log.warning(
            "grant_admin: promoted user_id=%s email=%s fields=%s",
            user.pk,
            user.email,
            changed,
        )
        self.stdout.write(f"Promoted {user.email}: set {', '.join(changed)}.")
