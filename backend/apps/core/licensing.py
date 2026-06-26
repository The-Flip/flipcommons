"""License display policy: kiosk-audience override and the minimum display rank."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Literal

# Maps Constance CONTENT_DISPLAY_POLICY choices to minimum permissiveness_rank.
DISPLAY_POLICY_RANKS: dict[str, int] = {
    "show-all": 0,  # Everything, including Not Allowed
    "include-unknown": 5,  # Unknown (null, rank 5) + all licensed content
    "licensed-only": 38,  # Lowest CC license (CC BY-NC-ND 2.0) and above
}

# Effective rank for null (unknown) license.
UNKNOWN_LICENSE_RANK = 5

# Per-request override: when True, the request is treated as the "kiosk"
# audience and sees show-all content, regardless of the global Constance
# policy. The override is task-local — it does not propagate across
# sync_to_async or threadpool boundaries.
_kiosk_audience: ContextVar[bool] = ContextVar("kiosk_audience", default=False)


def set_kiosk_audience() -> Token[bool]:
    """Mark the current request as the kiosk audience. Returns a Token for reset."""
    return _kiosk_audience.set(True)


def reset_kiosk_audience(token: Token[bool]) -> None:
    """Reset the kiosk-audience override using the token from set_kiosk_audience."""
    _kiosk_audience.reset(token)


def current_audience() -> Literal["kiosk", "default"]:
    """Return the active audience for the current request: ``"kiosk"`` or ``"default"``."""
    return "kiosk" if _kiosk_audience.get() else "default"


def get_minimum_display_rank() -> int:
    """Return the current minimum permissiveness_rank for displaying content."""
    if _kiosk_audience.get():
        return DISPLAY_POLICY_RANKS["show-all"]

    from constance import config

    return DISPLAY_POLICY_RANKS.get(config.CONTENT_DISPLAY_POLICY, 38)
