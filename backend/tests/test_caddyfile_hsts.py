"""Caddy owns HSTS policy (Django W004/W005/W021 are silenced).

This test catches accidental deletion or weakening of the directive in
the checked-in Caddyfile. Pinned to the exact value rather than to any
``max-age``, because HSTS is sticky: a shortened value is invisible to
browsers that already cached the longer one, so a downgrade would pass
an unpinned assertion while quietly diverging from the policy every
live client is still enforcing. See ``docs/Hosting.md`` § HSTS.
"""

from __future__ import annotations

import re

from django.conf import settings


def test_caddyfile_emits_hsts() -> None:
    caddyfile = (settings.BASE_DIR.parent / "Caddyfile").read_text()
    assert re.search(
        r'^\s*Strict-Transport-Security\s+"max-age=31536000"\s*$',
        caddyfile,
        re.MULTILINE,
    ), "Caddyfile must carry Strict-Transport-Security; see docs/Hosting.md § HSTS"
