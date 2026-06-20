"""Pure host helpers for citation-source recognition.

Model-free and dependency-free (no Public Suffix List), so ``models``,
``extractors``, ``seeding`` and migrations can import it without a cycle.
Everything here takes a **host**, not a URL — callers parse
``urlparse(url).hostname`` first and skip a ``None`` result.

These helpers implement a **longest label-boundary suffix** host match: given a
host and a set of candidate roots, the most-specific candidate wins — an asset
subdomain (``s4.american-pinball.com``) resolves to its registrable root, while
a more-specific seeded host (``twip.kineticist.com``) still beats its parent
domain for its own subtree. The intended consumer is citation-source
recognition; on their own these are pure string ops — deterministic and offline.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple


def normalize_host(hostname: str) -> str:
    """Normalize a host for recognition: lowercase, strip a leading ``www.``.

    The single chokepoint that makes ``CitationSourceRootDomain.host``'s
    ``unique`` meaningful — every write of a recognition host goes through here.
    Only a leading ``www.`` *label* is stripped (``wwworld.example.com`` keeps
    its first label). A trailing FQDN dot (``example.com.``) is dropped so it
    matches the same stored row as ``example.com``.
    """
    host = hostname.strip().lower().rstrip(".")
    return host.removeprefix("www.")


def label_suffixes(host: str) -> list[str]:
    """Every label-boundary suffix of a **normalized** *host*, longest first.

    ``"s4.american-pinball.com"`` →
    ``["s4.american-pinball.com", "american-pinball.com", "com"]``. An empty
    host yields ``[]``. Suffixes are taken at label (``.``) boundaries only, so
    ``"evil-american-pinball.com"`` is never a suffix of an
    ``"american-pinball.com"`` root.

    Expects *host* already run through :func:`normalize_host` — it splits on
    ``.`` verbatim and does not lowercase or strip ``www.``.
    """
    if not host:
        return []
    labels = host.split(".")
    return [".".join(labels[i:]) for i in range(len(labels))]


class RootDomainMatch(NamedTuple):
    """A seeded recognition host paired with the root source that owns it.

    ``host`` is expected normalized (see :func:`normalize_host`), as the DB
    write path stores it — :func:`longest_suffix_match` compares it verbatim.
    """

    source_id: int
    source_name: str
    host: str


def longest_suffix_match(
    url_host: str, domains: Sequence[RootDomainMatch]
) -> RootDomainMatch | None:
    """The most-specific *domains* row whose host is a suffix of *url_host*.

    The winner is the row whose ``host`` is the **longest label-boundary
    suffix** of *url_host* (``host == url_host`` or
    ``url_host.endswith("." + host)``). Returns ``None`` when nothing matches.
    Ties are impossible when candidate hosts are unique (as the seeded
    recognition rows are): no two share a host, and the strict ``>`` on length
    keeps the result independent of iteration order.

    Both sides must be normalized: *url_host* run through
    :func:`normalize_host` by the caller, and each ``domain.host`` stored
    normalized at write time. The comparison is exact (no lowercasing or
    ``www.`` stripping here), so a raw, mixed-case or ``www.``-prefixed
    *url_host* silently fails to match rather than being coerced.
    """
    candidates = set(label_suffixes(url_host))
    best: RootDomainMatch | None = None
    for domain in domains:
        if domain.host in candidates and (
            best is None or len(domain.host) > len(best.host)
        ):
            best = domain
    return best
