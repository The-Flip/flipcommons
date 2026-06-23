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

Everything here takes a :data:`~apps.citation.hosts.Host` (already normalized);
the dependency is one-way (``psl`` → ``hosts``, never back).
"""

from __future__ import annotations

from publicsuffixlist import PublicSuffixList

from apps.citation.hosts import Host

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
