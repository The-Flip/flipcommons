"""The User-Agent sent to servers this project does not own. See docs/UserAgent.md."""

from __future__ import annotations

from typing import Final

# The version marks a client-behavior generation, not a release: bump it when
# a site operator's rule for us would need revisiting, never on deploy, and
# never a git SHA (safe_fetch fetches user-supplied URLs and the repo is
# public). The URL is the canonical site, not SITE_ORIGIN, which is localhost
# in development. Must not start with `flipcommons-`, which production_logs/
# reads as probe traffic.
USER_AGENT: Final = "Flipcommons/1.0 (+https://flipcommons.org/about)"
