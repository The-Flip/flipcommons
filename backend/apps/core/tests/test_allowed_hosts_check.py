"""Tests for ``apps.core.checks.check_allowed_hosts_origin``.

The CDN sends the Railway origin hostname, so its absence from
ALLOWED_HOSTS answers every request with a 400. ``core.E307`` is the
operator-facing contract — pinned here so a message rewrite doesn't
silently break log greps.
"""

from __future__ import annotations

from pytest_django.fixtures import SettingsWrapper

from apps.core.checks import check_allowed_hosts_origin


class TestAllowedHostsOriginCheck:
    def test_passes_when_debug_is_true(self, settings: SettingsWrapper) -> None:
        settings.DEBUG = True
        settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
        assert check_allowed_hosts_origin(app_configs=None) == []

    def test_passes_when_the_origin_host_is_listed(
        self, settings: SettingsWrapper
    ) -> None:
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = [
            "flipcommons.org",
            "flipcommons-production.up.railway.app",
        ]
        assert check_allowed_hosts_origin(app_configs=None) == []

    def test_errors_when_only_public_hosts_are_listed(
        self, settings: SettingsWrapper
    ) -> None:
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = ["flipcommons.org", "www.flipcommons.org"]
        messages = check_allowed_hosts_origin(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E307"

    def test_a_wildcard_does_not_satisfy_the_check(
        self, settings: SettingsWrapper
    ) -> None:
        # "*" would accept the origin host, but it also accepts everything
        # else; the check exists to keep the allowlist explicit.
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = ["*"]
        messages = check_allowed_hosts_origin(app_configs=None)
        assert len(messages) == 1
        assert messages[0].id == "core.E307"
