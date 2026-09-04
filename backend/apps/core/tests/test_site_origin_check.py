"""Tests for ``apps.core.checks.check_site_origin``.

Guards the deploy-time contract that SITE_ORIGIN is set and well-formed
on every non-DEBUG deployment. The check ids (``core.E303``,
``core.E304``) are the operator-facing contract — pinned here so a
rename in the message string doesn't silently break log greps.
"""

from __future__ import annotations

import pytest
from pytest_django.fixtures import SettingsWrapper

from apps.core.checks import check_site_origin

MonkeyPatch = pytest.MonkeyPatch


class TestSiteOriginCheck:
    def test_passes_when_debug_is_true(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        # DEBUG short-circuits the check; `make dev` uses the localhost
        # fallback in svelte.config.js, so requiring an explicit value
        # locally would just add friction.
        settings.DEBUG = True
        monkeypatch.delenv("SITE_ORIGIN", raising=False)
        assert check_site_origin(app_configs=None) == []

    def test_passes_when_set_to_production_origin(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        settings.DEBUG = False
        monkeypatch.setenv("SITE_ORIGIN", "https://flipcommons.org")
        assert check_site_origin(app_configs=None) == []

    def test_errors_when_unset(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        settings.DEBUG = False
        monkeypatch.delenv("SITE_ORIGIN", raising=False)
        messages = check_site_origin(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E303"

    def test_whitespace_only_counts_as_empty(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        settings.DEBUG = False
        monkeypatch.setenv("SITE_ORIGIN", "   ")
        messages = check_site_origin(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E303"

    @pytest.mark.parametrize(
        "bad_value",
        [
            "http://flipcommons.org",  # http scheme rejected
            "flipcommons.org",  # no scheme
            "https://",  # scheme only
            "https://flipcommons.org/",  # trailing slash — would produce //paths
            "https://flipcommons.org/path",  # path
            "https://flipcommons.org?x=1",  # query
            "https://flipcommons.org#frag",  # fragment
            "not-a-url",
            "ftp://flipcommons.org",
        ],
    )
    def test_errors_when_malformed(
        self,
        settings: SettingsWrapper,
        monkeypatch: MonkeyPatch,
        bad_value: str,
    ) -> None:
        settings.DEBUG = False
        monkeypatch.setenv("SITE_ORIGIN", bad_value)
        messages = check_site_origin(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E304"

    def test_accepts_django_kwargs_forward_compat(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        settings.DEBUG = False
        monkeypatch.setenv("SITE_ORIGIN", "https://flipcommons.org")
        assert check_site_origin(app_configs=None, databases=["default"]) == []

    def test_reads_the_environment_not_the_setting(
        self, settings: SettingsWrapper, monkeypatch: MonkeyPatch
    ) -> None:
        # settings.SITE_ORIGIN carries a localhost fallback, so it is never
        # empty. Reading it here would make core.E303 unreachable and let an
        # unset variable through to production.
        settings.DEBUG = False
        settings.SITE_ORIGIN = "https://flipcommons.org"
        monkeypatch.delenv("SITE_ORIGIN", raising=False)
        messages = check_site_origin(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E303"
