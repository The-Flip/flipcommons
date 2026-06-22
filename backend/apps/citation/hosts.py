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
from typing import NamedTuple, NewType

Host = NewType("Host", str)
"""A recognition host **already normalized** by :func:`normalize_host`.

A marker over ``str`` that pins the normalize-before-compare precondition at the
type level: the suffix helpers and :func:`longest_suffix_match` accept only a
``Host``, so passing a raw ``urlparse(...).hostname`` is a type error, not a
silent non-match. Its only honest sources are :func:`normalize_host` and a value
read from ``CitationSourceRootDomain.host`` (stored normalized by the model's
``clean()``). ``NewType`` does not *validate*, so don't fabricate a ``Host`` from
an un-normalized string outside those paths.
"""


def normalize_host(hostname: str) -> Host:
    """Normalize a host for recognition: lowercase, strip all leading ``www.``.

    The single chokepoint that makes ``CitationSourceRootDomain.host``'s
    ``unique`` meaningful — every write of a recognition host goes through here.
    **All** consecutive leading ``www.`` *labels* are stripped
    (``www.www.foo.com`` → ``foo.com``), so the result can't shadow the bare
    domain — a single strip would leave ``www.foo.com``, a distinct stored host
    from ``foo.com``. Only whole ``www.`` labels are stripped, so
    ``wwworld.example.com`` keeps its first label. A trailing FQDN dot
    (``example.com.``) is dropped so it matches the same stored row as
    ``example.com``. Idempotent: ``normalize_host(normalize_host(x))`` equals
    ``normalize_host(x)``. The result is a :data:`Host`.
    """
    host = hostname.strip().lower().rstrip(".")
    while host.startswith("www."):
        host = host.removeprefix("www.")
    return Host(host)


def label_suffixes(host: Host) -> list[Host]:
    """Every label-boundary suffix of a normalized *host*, longest first.

    ``"s4.american-pinball.com"`` →
    ``["s4.american-pinball.com", "american-pinball.com", "com"]``. An empty
    host yields ``[]``. Suffixes are taken at label (``.``) boundaries only, so
    ``"evil-american-pinball.com"`` is never a suffix of an
    ``"american-pinball.com"`` root.

    Takes a :data:`Host` — splitting a normalized host on ``.`` yields
    normalized suffixes, so it neither lowercases nor strips ``www.`` here.
    """
    if not host:
        return []
    labels = host.split(".")
    return [Host(".".join(labels[i:])) for i in range(len(labels))]


class RootDomainMatch(NamedTuple):
    """A seeded recognition host paired with the root source that owns it.

    ``host`` is a :data:`Host` — normalized, as the DB write path stores it, so
    :func:`longest_suffix_match` compares it verbatim.
    """

    source_id: int
    source_name: str
    host: Host


def longest_suffix_match(
    url_host: Host, domains: Sequence[RootDomainMatch]
) -> RootDomainMatch | None:
    """The most-specific *domains* row whose host is a suffix of *url_host*.

    The winner is the row whose ``host`` is the **longest label-boundary
    suffix** of *url_host* (``host == url_host`` or
    ``url_host.endswith("." + host)``). Returns ``None`` when nothing matches.
    Ties are impossible when candidate hosts are unique (as the seeded
    recognition rows are): no two share a host, and the strict ``>`` on length
    keeps the result independent of iteration order.

    Both sides are :data:`Host` (normalized) by type — *url_host* via
    :func:`normalize_host`, each ``domain.host`` stored normalized at write
    time. The comparison is exact (no lowercasing or ``www.`` stripping here);
    the :data:`Host` requirement is what stops a raw, mixed-case or
    ``www.``-prefixed host from reaching it and silently missing.
    """
    candidates = set(label_suffixes(url_host))
    best: RootDomainMatch | None = None
    for domain in domains:
        if domain.host in candidates and (
            best is None or len(domain.host) > len(best.host)
        ):
            best = domain
    return best
