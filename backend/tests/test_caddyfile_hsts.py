"""Caddy owns HSTS policy (Django W004/W005/W021 are silenced).

This test catches accidental deletion or weakening of the directive in
the checked-in Caddyfile. Pinned to the exact current ratchet value so
each ratchet step (#462, #463) updates Caddyfile and test together —
that symmetry makes step-skipping and downgrades impossible to do by
halves. See ``docs/Hosting.md`` § HSTS.
"""

from __future__ import annotations

import re

from django.conf import settings


def test_caddyfile_emits_hsts() -> None:
    caddyfile = (settings.BASE_DIR.parent / "Caddyfile").read_text()
    assert re.search(
        r'^\s*Strict-Transport-Security\s+"max-age=60"\s*$',
        caddyfile,
        re.MULTILINE,
    ), "Caddyfile must carry Strict-Transport-Security; see docs/Hosting.md § HSTS"
