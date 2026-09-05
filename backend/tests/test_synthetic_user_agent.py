"""The probe user-agent must keep the prefix `is_synthetic_ua` matches on.

That macro lives in production_logs/analyze/sql/00_reference.sql and cannot
import this value, so the convention is enforced here.
"""

from __future__ import annotations

from edge_tests.probe import USER_AGENT

SYNTHETIC_UA_PREFIX = "flipcommons-"


def test_edge_probe_user_agent_keeps_the_synthetic_prefix() -> None:
    assert USER_AGENT.startswith(SYNTHETIC_UA_PREFIX), (
        f"the edge smoke suite sends User-Agent {USER_AGENT!r}, which "
        f"is_synthetic_ua() does not match: its requests would be counted as "
        "real traffic in bunny_requests and railway_requests"
    )
