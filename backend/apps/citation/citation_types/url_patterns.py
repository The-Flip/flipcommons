"""Reusable URL-pattern fragments for scheme authors.

Pure regex helpers that factor the two error-prone, repeated pieces of a
scheme's ``url_pattern``: the anchored, dot-escaped host prefix and the path-id
boundary. A scheme composes them with its own path grammar; genuinely weird
shapes (Vimeo's unlisted-hash tail, X's media tails) still spell out raw regex.

A dependency-free leaf like ``base.py`` — imported by scheme modules, imports
no app code.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# The path-id boundary shared by path-style schemes (YouTube's
# /embed//shorts//live/, Vimeo's embed, TikTok): the captured id may be followed
# by a single trailing slash, then only a query, a fragment, or the end — never
# more path, so ``/<id>/extra`` fails instead of collapsing to a valid-looking
# id. Append it directly after a capture group.
ID_BOUNDARY = r"(?=/?(?:[?#]|$))"


def host_prefix(*hosts: str, subdomains: Sequence[str] = ("www",)) -> str:
    """The anchored, dot-escaped host portion of a scheme ``url_pattern``.

    Returns ``https?://`` + an optional subdomain + one of the *hosts*, each
    ``re.escape``-d. The escaping is the point: an unescaped ``youtube.com``
    lets its dots match any character, so ``notyoutubeXcom`` would recognize —
    the look-alike-host bug the conformance harness guards against. Append the
    scheme's path pattern to the result.

    *subdomains* are optional leading labels (``"www"`` → an optional ``www.``);
    pass ``()`` for a host that takes none (``player.vimeo.com``). Only
    non-capturing groups are emitted, so the scheme's own id capture stays the
    pattern's sole group — ``SchemeSpec.extract`` reads the identifier by
    ``lastindex``.
    """
    hosts_alt = "|".join(re.escape(h) for h in hosts)
    if not subdomains:
        return rf"https?://(?:{hosts_alt})"
    prefix = "|".join(re.escape(s) + r"\." for s in subdomains)
    return rf"https?://(?:{prefix})?(?:{hosts_alt})"
