"""The public API's edge cache policy, as published to its consumers."""

from __future__ import annotations

import pytest

from apps.core.cache_control import (
    PUBLIC_API_EDGE_TTL,
    humanize_seconds,
    public_api_freshness_summary,
)


@pytest.mark.parametrize(
    ("seconds", "words"),
    [(60, "1 minute"), (300, "5 minutes"), (3600, "1 hour"), (86400, "24 hours")],
)
def test_humanize_seconds(seconds: int, words: str) -> None:
    assert humanize_seconds(seconds) == words


def test_freshness_summary_is_derived_from_the_ttl() -> None:
    assert public_api_freshness_summary() == humanize_seconds(PUBLIC_API_EDGE_TTL)


def test_published_description_states_the_freshness_window() -> None:
    """The number consumers read must track the constant."""
    from config.api import public_api

    assert public_api_freshness_summary() in public_api.description
