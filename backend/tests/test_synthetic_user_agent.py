"""The `flipcommons-` User-Agent prefix means probe traffic, and nothing else.

`is_synthetic_ua` in production_logs/analyze/sql/00_reference.sql matches that
prefix case-insensitively and cannot import these values, so both sides of the
convention are pinned here. The copy in production_logs/pull/pull_common.py is
out of reach.
"""

from __future__ import annotations

from apps.core.user_agent import USER_AGENT as OUTWARD_USER_AGENT
from edge_tests.probe import USER_AGENT as PROBE_USER_AGENT

SYNTHETIC_UA_PREFIX = "flipcommons-"


def test_edge_probe_user_agent_keeps_the_synthetic_prefix() -> None:
    assert PROBE_USER_AGENT.startswith(SYNTHETIC_UA_PREFIX), (
        f"the edge smoke suite sends User-Agent {PROBE_USER_AGENT!r}, which "
        f"is_synthetic_ua() does not match: its requests would be counted as "
        "real traffic in bunny_requests and railway_requests"
    )


def test_outward_user_agent_is_never_mistaken_for_a_probe() -> None:
    assert not OUTWARD_USER_AGENT.lower().startswith(SYNTHETIC_UA_PREFIX), (
        f"is_synthetic_ua() would match {OUTWARD_USER_AGENT!r}, dropping real "
        "traffic from the health views as a probe"
    )
