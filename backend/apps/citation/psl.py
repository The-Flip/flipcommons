"""Public Suffix List boundary for citation-source recognition.

The one module that depends on the bundled Public Suffix List
(``publicsuffixlist``). Kept separate from :mod:`apps.citation.hosts` — which is
deliberately pure and PSL-free — so the recognition *read* path
(:mod:`apps.citation.extractors`) never pulls the snapshot in transitively. Only
the *write-time* guard (``CitationSourceRootDomain.clean``) and the *derive*
funnel (``cite-url``'s no-match branch) consult the PSL.

The list is loaded **once at import** into a module-level ``PublicSuffixList``.
``accept_unknown=True`` fails open on a gTLD newer than the bundled snapshot — a
genuinely-unknown but real TLD rounds rather than 422-ing; the RFC special-use
names are still rejected separately by :func:`apps.citation.hosts.is_reserved_tld`.
``only_icann=False`` (the default) honors the PRIVATE section, so ``github.io``
is itself a public suffix and ``foo.github.io`` is one whole site.

The two predicates take a :data:`~apps.citation.hosts.Host` (already normalized).
The one exception is :func:`root_host_from_url` — the *derive funnel*, which
takes a raw URL and is the single place that parses, validates and rounds an
untrusted contributor paste into a storable recognition host. The dependency is
one-way (``psl`` → ``hosts``, never back).
"""

from __future__ import annotations

import enum
from urllib.parse import urlparse

from publicsuffixlist import PublicSuffixList

from apps.citation.hosts import (
    Host,
    is_dns_host,
    is_reserved_tld,
    normalize_host,
)
from apps.citation.shared_hosts import shared_host_for

# Built once at import — parsing the bundled snapshot is a cost paid a single
# time, and this is the module's only ``Any`` boundary (publicsuffixlist ships
# no py.typed). ``accept_unknown`` fails open on unknown-but-real TLDs;
# ``only_icann`` stays False so PRIVATE-section suffixes (``github.io``) count.
_PSL = PublicSuffixList(accept_unknown=True, only_icann=False)


def is_public_suffix(host: Host) -> bool:
    """Whether *host* is itself a public suffix (no registrable label below it).

    ``gov.uk``, ``co.uk``, ``com`` and PRIVATE-section names like ``github.io``
    are public suffixes; ``dvla.gov.uk`` and ``american-pinball.com`` are not. A
    bare public suffix must never be stored as a recognition host — under
    longest-suffix matching it would over-match every unrelated site beneath it,
    which is exactly what the ``CitationSourceRootDomain.clean`` guard prevents.

    Equivalent to ``registrable_domain(host) is None`` for any DNS-valid host;
    the two are cross-checked by test against the bundled snapshot.
    """
    return bool(host) and _PSL.publicsuffix(host) == host


def registrable_domain(host: Host) -> Host | None:
    """The registrable domain of *host* — its public suffix plus one label.

    ``s4.american-pinball.com`` → ``american-pinball.com``; ``a.b.co.uk`` →
    ``b.co.uk``; ``foo.github.io`` → ``foo.github.io`` (PRIVATE section). Returns
    ``None`` when *host* is itself a bare public suffix (:func:`is_public_suffix`)
    — there is no domain to round to. This is the rounding step the derive funnel
    uses to collapse a fuzzy subdomain cite to one root.
    """
    private = _PSL.privatesuffix(host)
    return Host(private) if private else None


class HostRejection(enum.Enum):
    """Why :func:`root_host_from_url` refused to round a pasted URL to a host.

    One member per gate in the funnel, in gate order. The cite-url boundary maps
    each to a specific 422 message; the value is a stable machine reason.
    """

    NO_HOST = "no_host"
    """The URL has no host component to root a site on."""
    NOT_DNS = "not_dns"
    """The host isn't a DNS hostname — an IP literal or a malformed/raw-IDN host."""
    RESERVED_TLD = "reserved_tld"
    """The host's TLD is an RFC special-use name (``.test``, ``.example``, …)."""
    PUBLIC_SUFFIX = "public_suffix"
    """The host is a bare public suffix (``gov.uk``, ``co.uk``) with no domain below."""
    SHARED_HOST = "shared_host"
    """The host is a declared shared multi-tenant CDN — no maker's site to root."""


class HostError(Exception):
    """A pasted URL could not be rounded to a storable recognition host.

    Raised only by :func:`root_host_from_url`, and carries a typed
    :class:`HostRejection` so the ``cite-url`` boundary can map each rejection to
    a specific 422. Deliberately **not** an ``HttpError`` — this module is
    HTTP-free, so the funnel stays unit-testable apart from the API layer.
    """

    def __init__(self, reason: HostRejection) -> None:
        super().__init__(reason.value)
        self.reason = reason


def root_host_from_url(url: str) -> Host:
    """Round a pasted page URL to the registrable domain to root a new site on.

    The **derive funnel**: the one place the system turns an untrusted
    contributor URL into a stored recognition host. HTTP-free — it parses and
    validates only, never fetches. Gates run in this order, each raising
    :class:`HostError` with the matching :class:`HostRejection`:

    1. ``urlparse(url).hostname`` parses and is present — a parser failure
       (e.g. an unterminated IPv6 bracket, which raises ``ValueError``) maps to
       ``NOT_DNS``; a missing host maps to ``NO_HOST``.
    2. :func:`~apps.citation.hosts.is_dns_host` after
       :func:`~apps.citation.hosts.normalize_host` — else ``NOT_DNS`` (IP
       literal, raw-unicode IDN, malformed host).
    3. **not** :func:`~apps.citation.hosts.is_reserved_tld` — else
       ``RESERVED_TLD``. This reject is funnel-only: a fuzzy paste must not mint
       a root that could never match a real cite. The declare path
       (``CitationSourceRootDomain.clean``) skips it — declaring is curator-trusted.
    4. **not** :func:`~apps.citation.shared_hosts.shared_host_for` — else
       ``SHARED_HOST``. A shared multi-tenant CDN host is nobody's site: the
       tenant lives in the path, so rounding a paste there would mint a root
       (``wsimg.com``) that absorbs every tenant's files. Checked on the
       *pasted* host, before rounding, so an asset-subdomain paste can't
       sidestep it. A maker's slice of a shared host is declared by a curator
       with a ``path_prefix``, never derived from a paste.
    5. :func:`registrable_domain` is not ``None`` — else ``PUBLIC_SUFFIX`` (a
       bare public suffix has no registrable label to round to).

    Returns the **registrable domain** (``s4.american-pinball.com`` →
    ``american-pinball.com``), so future cites under the same site collapse to
    one root — the anti-fragmentation goal. The order is intentional:
    ``is_reserved_tld`` runs before :func:`registrable_domain` because
    ``accept_unknown=True`` would otherwise round a reserved name to itself.
    """
    try:
        hostname = urlparse(url).hostname
    except ValueError as exc:
        # urlparse rejects some malformed URLs (e.g. an unterminated IPv6
        # bracket) by raising rather than returning a host. Surface it as a
        # typed reject so the API boundary 422s instead of 500-ing.
        raise HostError(HostRejection.NOT_DNS) from exc
    if hostname is None:
        raise HostError(HostRejection.NO_HOST)
    host = normalize_host(hostname)
    if not is_dns_host(host):
        raise HostError(HostRejection.NOT_DNS)
    if is_reserved_tld(host):
        raise HostError(HostRejection.RESERVED_TLD)
    if shared_host_for(host) is not None:
        raise HostError(HostRejection.SHARED_HOST)
    rounded = registrable_domain(host)
    if rounded is None:
        raise HostError(HostRejection.PUBLIC_SUFFIX)
    return rounded
