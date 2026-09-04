"""Tests for ``apps.core.site_origin``."""

from __future__ import annotations

from pytest_django.fixtures import SettingsWrapper

from apps.core.site_origin import absolute_site_url, site_host


class TestSiteHost:
    def test_keeps_the_port(self, settings: SettingsWrapper) -> None:
        settings.SITE_ORIGIN = "http://localhost:5173"
        assert site_host() == "localhost:5173"

    def test_production_origin(self, settings: SettingsWrapper) -> None:
        settings.SITE_ORIGIN = "https://flipcommons.org"
        assert site_host() == "flipcommons.org"


class TestAbsoluteSiteUrl:
    def test_resolves_a_root_relative_path(self, settings: SettingsWrapper) -> None:
        settings.SITE_ORIGIN = "https://flipcommons.org"
        assert absolute_site_url("/") == "https://flipcommons.org/"

    def test_resolves_a_path_without_a_leading_slash(
        self, settings: SettingsWrapper
    ) -> None:
        settings.SITE_ORIGIN = "https://flipcommons.org"
        assert absolute_site_url("goodbye") == "https://flipcommons.org/goodbye"

    def test_tolerates_a_trailing_slash_on_the_origin(
        self, settings: SettingsWrapper
    ) -> None:
        settings.SITE_ORIGIN = "https://flipcommons.org/"
        assert absolute_site_url("/bye") == "https://flipcommons.org/bye"

    def test_passes_an_absolute_url_through(self, settings: SettingsWrapper) -> None:
        settings.SITE_ORIGIN = "https://flipcommons.org"
        assert absolute_site_url("https://elsewhere.test/x") == (
            "https://elsewhere.test/x"
        )
