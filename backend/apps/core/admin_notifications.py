"""Best-effort notifications to the Admin Discord channel. Not Django admin UI.

Delivery is one blocking POST with a hard timeout, no retries and no queue:
every announced event is already durably recorded, so a dropped notification
loses a ping, never data. See docs/Observability.md for the rationale and the
no-personal-data rule for the payload.
"""

from __future__ import annotations

import json
import logging
from urllib.request import Request, urlopen

import sentry_sdk
from django.conf import settings

from apps.core.user_agent import USER_AGENT

logger = logging.getLogger(__name__)


class AdminNotificationError(Exception):
    """A notification was not delivered. Raised only into Sentry, never to callers."""


# Per socket operation, not a wall-clock deadline, so the practical ceiling is
# a small multiple of this. Well inside gunicorn's 60s worker timeout.
_TIMEOUT_SECONDS = 2

# Discord's limit on ``content``. Truncate rather than fail.
_MAX_CONTENT_LEN = 2000


def notify_admins(code: str, message: str) -> None:
    """Post ``message`` to the Admin channel. Never raises.

    ``code`` names the event (``"account.created"``) in the failure log. Every
    exception is swallowed because callers run this from
    ``transaction.on_commit``, where a raise propagates into the request that
    just committed.
    """
    webhook_url: str = settings.ADMIN_NOTIFICATION_WEBHOOK_URL
    if not webhook_url:
        return
    try:
        body = json.dumps({"content": message[:_MAX_CONTENT_LEN]}).encode()
        req = Request(  # noqa: S310 — settings validation guarantees https://
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        with urlopen(req, timeout=_TIMEOUT_SECONDS):  # noqa: S310 — settings validation guarantees https://
            pass
    except Exception as exc:
        # Wrapped so the issue is titled by what failed, a notification,
        # rather than by whatever urllib raised; the cause stays in the value.
        error = f"{type(exc).__name__}: {exc}"
        logger.error("admin_notification.failed", extra={"code": code, "error": error})
        sentry_sdk.capture_exception(AdminNotificationError(error))
