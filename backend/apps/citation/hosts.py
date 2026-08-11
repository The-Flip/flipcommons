"""Pure host and path-prefix helpers for citation-source recognition.

Model-free and dependency-free (no Public Suffix List), so ``models``,
``extractors``, ``source_upsert`` and migrations can import it without a cycle.
Everything here takes a **host** (and, where paths participate, a URL *path*),
never a whole URL — callers parse ``urlparse(url)`` first and skip a ``None``
hostname.

These helpers implement a **longest label-boundary suffix** host match: given a
host and a set of candidate roots, the most-specific candidate wins — an asset
subdomain (``s4.american-pinball.com``) resolves to its registrable root, while
a more-specific seeded host (``twip.kineticist.com``) still beats its parent
domain for its own subtree. A candidate may additionally be scoped by a
**path prefix** (a shared CDN's per-tenant directory); such a row matches only
URLs whose path sits under the prefix at a segment boundary, and among matching
rows host specificity dominates path specificity. The intended consumer is
citation-source recognition; on their own these are pure string ops —
deterministic and offline.

This module also carries the **syntactic** host predicates
(:func:`is_dns_host`, :func:`is_reserved_tld`) that the write-time guard and the
derive funnel gate on — pure string / ``ipaddress`` checks, no DNS lookup. The
two **PSL-backed** predicates (``is_public_suffix``, ``registrable_domain``)
deliberately live in :mod:`apps.citation.psl` instead, so this module stays
dependency-free and the recognition read path never imports the snapshot.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from typing import NamedTuple, NewType

from apps.core.types import CitationSourceId

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


PathPrefix = NewType("PathPrefix", str)
"""A recognition path prefix **already normalized** by :func:`normalize_path_prefix`.

The path half of a path-scoped recognition row: ``""`` for a bare-host row
(matches every path — today's semantics), otherwise a ``/``-led,
non-``/``-terminated URL-path prefix stored **verbatim** — case-sensitive, no
percent-decoding — matched at path-segment boundaries only. Like :data:`Host`,
``NewType`` does not validate; the honest sources are
:func:`normalize_path_prefix` and a value read from
``CitationSourceRootDomain.path_prefix`` (stored normalized by the model's
``clean()``).
"""


def normalize_path_prefix(raw: str) -> PathPrefix:
    """Normalize a path prefix: trim, lead with exactly one ``/``, no trailing ``/``.

    The write-path chokepoint for ``CitationSourceRootDomain.path_prefix``,
    mirroring :func:`normalize_host` for hosts. Deliberately **not** lowercased
    and **not** percent-decoded — URL paths are case-sensitive and a shared
    CDN's tenant ids are matched verbatim; only the slash framing is
    canonicalized so ``blobby/go/x``, ``/blobby/go/x`` and ``/blobby/go/x/``
    all store one shape. Whitespace-only and bare-``/`` input normalize to
    ``""`` (the bare-host form). Idempotent. The result is a
    :data:`PathPrefix`; syntactic validity is :func:`is_path_prefix`'s job.
    """
    prefix = raw.strip()
    prefix = prefix.rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    return PathPrefix(prefix)


# A path segment that traverses: ``.`` or ``..`` spelled literally or with
# percent-encoded dots (``%2e``, any case), in any 1–2-unit combination
# (``.``, ``..``, ``%2e``, ``%2e%2e``, ``.%2e``, ``%2e.``).
_TRAVERSAL_SEGMENT = re.compile(r"(?:\.|%2e){1,2}", re.IGNORECASE)


def is_traversal_free_path(url_path: str) -> bool:
    """Whether *url_path* is free of dot-segment / backslash traversal.

    ``urlparse`` does not normalize dot segments but browsers and CDNs do, so
    ``/tenant/../other`` (or its ``%2e`` / backslash spellings) would match
    under ``/tenant`` while actually fetching another tenant's file. Recognition
    must not claim a page it can't honestly resolve, so a path-scoped row
    refuses such a path outright (reject, not canonicalize); bare-host rows are
    unaffected — their attribution doesn't depend on the path.
    """
    if "\\" in url_path:
        return False
    return not any(
        _TRAVERSAL_SEGMENT.fullmatch(segment) for segment in url_path.split("/")
    )


def is_path_prefix(prefix: PathPrefix) -> bool:
    """Whether *prefix* is syntactically a valid recognition path prefix.

    ``""`` (the bare-host form) is valid. Otherwise: must start with ``/``,
    must not end with ``/``, no ``?``/``#`` (querystrings and fragments never
    participate in recognition), no empty segments (``//``), and no traversal
    segments (:func:`is_traversal_free_path` — a stored ``/tenant/..`` prefix
    could never match honestly). Length is the storage column's concern.
    Expects a normalized :data:`PathPrefix`.
    """
    if prefix == "":
        return True
    if not prefix.startswith("/") or prefix.endswith("/"):
        return False
    if "?" in prefix or "#" in prefix:
        return False
    if any(segment == "" for segment in prefix.split("/")[1:]):
        return False
    return is_traversal_free_path(prefix)


def path_prefix_matches(prefix: PathPrefix, url_path: str) -> bool:
    """Whether *url_path* sits under *prefix* at a path-segment boundary.

    A bare prefix (``""``) matches every path. A non-bare prefix matches the
    exact path or any path below it — the segment boundary
    (``prefix + "/"``) is what stops ``/blobby/go/4bd466e8-evil…`` matching a
    ``/blobby/go/4bd466e8-…`` prefix. Comparison is verbatim: case-sensitive,
    percent-encoding untouched. A traversal-carrying *url_path* never matches
    a non-bare prefix (see :func:`is_traversal_free_path`).
    """
    if prefix == "":
        return True
    if not is_traversal_free_path(url_path):
        return False
    return url_path == prefix or url_path.startswith(prefix + "/")


# A single DNS label: ASCII ``[a-z0-9-]``, 1–63 chars, no leading/trailing
# hyphen. The charset is pinned ASCII on purpose — ``str.isalnum()`` is
# unicode-true and would admit raw IDN. ``normalize_host`` lowercases first, so
# the class needs no uppercase range.
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

# RFC 6761 / 6762 special-use top-level names: reserved by the standards bodies
# to *never* be real registrable domains. A standards constant, not a denylist.
_RESERVED_TLDS = frozenset({"localhost", "invalid", "test", "example", "local"})


def is_dns_host(host: Host) -> bool:
    """Whether *host* is syntactically a DNS hostname (not an IP literal).

    Syntactic only — no DNS lookup, no PSL. Rejects IP literals (``127.0.0.1``,
    ``::1``, bracket-stripped) and requires dot-separated :data:`_DNS_LABEL`
    labels — at least one dot, a total length within the 253-char hostname
    limit, and a non-all-numeric rightmost label (an all-numeric TLD is an IPv4
    shape that slipped the literal check). Accepts punycode (``xn--…``);
    raw-unicode IDN is rejected by the ASCII label charset — a known limitation
    (an internationalized recognition host must be punycode). Expects a
    normalized :data:`Host`.
    """
    # The full presentation hostname tops out at 253 chars (the RFC 1035
    # 255-octet wire limit minus the length/root bytes). Owned here so the
    # syntactic contract is complete, not delegated to the storage column.
    if not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        return False
    labels = host.split(".")
    if len(labels) < 2:
        return False
    if not all(_DNS_LABEL.fullmatch(label) for label in labels):
        return False
    return not labels[-1].isdigit()


def is_reserved_tld(host: Host) -> bool:
    """Whether *host*'s rightmost label is an RFC special-use TLD.

    ``foo.test``, ``bar.localhost`` and a bare ``invalid`` are reserved; a real
    registrable domain is not. The derive funnel (``cite-url``) rejects these so
    a fuzzy contributor paste can't mint a root that could never match a real
    cite; the declare path (``clean()``) deliberately does **not** — declaring a
    host is curator-trusted, and the citation test fixtures lean on ``.example``.
    Expects a normalized :data:`Host`.
    """
    return host.split(".")[-1] in _RESERVED_TLDS


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

    ``host`` is a :data:`Host` and ``path_prefix`` a :data:`PathPrefix` —
    both normalized, as the DB write path stores them, so
    :func:`longest_suffix_match` compares them verbatim. ``path_prefix`` is
    ``""`` for a bare-host row (matches every path).
    """

    source_id: CitationSourceId
    source_name: str
    host: Host
    path_prefix: PathPrefix = PathPrefix("")


def longest_suffix_match(
    url_host: Host, url_path: str, domains: Sequence[RootDomainMatch]
) -> RootDomainMatch | None:
    """The most-specific *domains* row matching *url_host* and *url_path*.

    A row is eligible when its ``host`` is a **label-boundary suffix** of
    *url_host* (``host == url_host`` or ``url_host.endswith("." + host)``)
    and its ``path_prefix`` matches *url_path* at a segment boundary
    (:func:`path_prefix_matches`; a bare row matches every path). Among
    eligible rows the winner has the longest host, then the longest prefix —
    host specificity dominates path specificity. Returns ``None`` when nothing
    matches.

    Ties are impossible when rows are unique on ``(host, path_prefix)`` (as
    the seeded recognition rows are): equal-length label-boundary suffixes of
    one host are the same host, equal-length matching prefixes of one path are
    the same prefix, and the strict ``>`` keeps the result independent of
    iteration order.

    *url_host* is a :data:`Host` (via :func:`normalize_host`) and each row's
    ``host``/``path_prefix`` are stored normalized at write time. The
    comparison is exact — no lowercasing, ``www.`` stripping or
    percent-decoding here; the :data:`Host` requirement is what stops a raw,
    mixed-case or ``www.``-prefixed host from reaching it and silently
    missing. *url_path* is the raw ``urlparse(url).path``.
    """
    candidates = set(label_suffixes(url_host))
    best: RootDomainMatch | None = None
    for domain in domains:
        if domain.host not in candidates:
            continue
        if not path_prefix_matches(domain.path_prefix, url_path):
            continue
        if best is None or (len(domain.host), len(domain.path_prefix)) > (
            len(best.host),
            len(best.path_prefix),
        ):
            best = domain
    return best
