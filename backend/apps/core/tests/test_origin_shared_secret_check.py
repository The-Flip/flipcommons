"""Tests for ``apps.core.checks.check_origin_shared_secret``.

Guards the deploy-time contract behind the Caddyfile origin gate: the
secret is set on every non-DEBUG deployment and drawn from the charset
the Caddy matcher can compare verbatim. The check ids (``core.E305``,
``core.E306``) are the operator-facing contract, pinned here so a
rename in the message string doesn't silently break log greps.
"""

from __future__ import annotations

import pytest
from pytest_django.fixtures import SettingsWrapper

from apps.core.checks import check_origin_shared_secret

MonkeyPatch = pytest.MonkeyPatch


class TestOriginSharedSecretCheck:
    def test_passes_when_debug_is_true(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        # `make dev` runs no Caddy, so a local value would gate nothing.
        settings.DEBUG = True
        monkeypatch.delenv("ORIGIN_SHARED_SECRET", raising=False)
        assert check_origin_shared_secret(app_configs=None) == []

    @pytest.mark.parametrize(
        "value",
        ["a", "0123456789", "abc_DEF-123", "-_-", "x" * 200],
    )
    def test_passes_on_the_caddy_safe_charset(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch, value: str
    ) -> None:
        settings.DEBUG = False
        monkeypatch.setenv("ORIGIN_SHARED_SECRET", value)
        assert check_origin_shared_secret(app_configs=None) == []

    def test_errors_when_unset(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        settings.DEBUG = False
        monkeypatch.delenv("ORIGIN_SHARED_SECRET", raising=False)
        messages = check_origin_shared_secret(app_configs=None)
        assert [m.id for m in messages] == ["core.E305"]

    def test_whitespace_only_counts_as_empty(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        settings.DEBUG = False
        monkeypatch.setenv("ORIGIN_SHARED_SECRET", "   ")
        messages = check_origin_shared_secret(app_configs=None)
        assert [m.id for m in messages] == ["core.E305"]

    @pytest.mark.parametrize(
        "bad_value",
        [
            " secret",  # leading whitespace: a second Caddyfile token
            "secret ",  # trailing whitespace
            "sec ret",
            '"secret"',  # quotes change tokenization
            "{secret}",  # braces are placeholder syntax
            "*secret",  # leading * makes the matcher a suffix match
            "secret*",  # trailing * makes it a prefix match
            "sec*ret",
            "secret\n",
            "sécret",
            "secret=1",
        ],
    )
    def test_errors_when_malformed(
        self,
        settings: SettingsWrapper,
        monkeypatch: MonkeyPatch,
        bad_value: str,
    ) -> None:
        settings.DEBUG = False
        monkeypatch.setenv("ORIGIN_SHARED_SECRET", bad_value)
        messages = check_origin_shared_secret(app_configs=None)
        assert [m.id for m in messages] == ["core.E306"]

    def test_messages_never_echo_the_value(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        # Deploy logs are shared; a malformed secret is still a secret.
        settings.DEBUG = False
        monkeypatch.setenv("ORIGIN_SHARED_SECRET", "hunter2 with spaces")
        messages = check_origin_shared_secret(app_configs=None)
        assert "hunter2" not in messages[0].msg
        assert "hunter2" not in (messages[0].hint or "")
