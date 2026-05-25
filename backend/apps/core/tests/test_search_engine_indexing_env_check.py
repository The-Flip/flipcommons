"""Tests for ``apps.core.checks.check_search_engine_indexing_env``.

Guards the deploy-time contract that every deployed service explicitly
declares its crawler-indexing intent via ``ALLOW_SEARCH_ENGINE_INDEXING``.
The check ids (``core.E301``, ``core.E302``) are the operator-facing
contract — pinned here so a rename in the message string doesn't silently
break log greps.
"""

from __future__ import annotations

import pytest

from apps.core.checks import check_search_engine_indexing_env

MonkeyPatch = pytest.MonkeyPatch


class TestSearchEngineIndexingEnvCheck:
    def test_passes_when_set_to_true(self, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOW_SEARCH_ENGINE_INDEXING", "true")
        assert check_search_engine_indexing_env(app_configs=None) == []

    def test_passes_when_set_to_false(self, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOW_SEARCH_ENGINE_INDEXING", "false")
        assert check_search_engine_indexing_env(app_configs=None) == []

    def test_errors_when_unset(self, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.delenv("ALLOW_SEARCH_ENGINE_INDEXING", raising=False)
        messages = check_search_engine_indexing_env(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E301"

    @pytest.mark.parametrize(
        "bad_value",
        [
            "   ",  # whitespace only
            " true ",  # the failure mode the no-strip rule defends
            "true ",
            " true",
            "\ttrue",
            "true\n",
            "True",  # capitalised — the SvelteKit helper rejects this
            "1",
            "yes",
            "on",
            "False",
            "0",
            "no",
            "off",
            "maybe",
        ],
    )
    def test_errors_when_malformed(
        self, monkeypatch: MonkeyPatch, bad_value: str
    ) -> None:
        # A typo like "True" or a stray space silently disabling production
        # indexing (because the SvelteKit helper only accepts the literal
        # "true") is exactly the failure mode the check exists to prevent.
        monkeypatch.setenv("ALLOW_SEARCH_ENGINE_INDEXING", bad_value)
        messages = check_search_engine_indexing_env(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E302"

    def test_accepts_django_kwargs_forward_compat(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALLOW_SEARCH_ENGINE_INDEXING", "true")
        assert (
            check_search_engine_indexing_env(app_configs=None, databases=["default"])
            == []
        )
