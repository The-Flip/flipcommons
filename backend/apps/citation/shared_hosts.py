"""Declared shared-CDN hosts — multi-tenant hosts where the path names the tenant.

A **shared host** serves many unrelated publishers' files under one hostname,
with the owning tenant identified only by a path segment: GoDaddy Website
Builder sites publish their documents on ``img1.wsimg.com`` under a per-tenant
``/blobby/go/<uuid>`` directory. Host-only recognition cannot attribute such a
URL — a bare recognition row for the host would resolve **every** tenant's
files to one publisher — so on these hosts recognition is path-scoped:

- ``CitationSourceRootDomain.clean()`` rejects a **bare** registration (no
  ``path_prefix``) on a shared host, and rejects a ``path_prefix`` anywhere
  *else* — path scoping exists for shared hosts only.
- Recognition (``extractors``) ignores bare rows outright when a URL's host is
  shared, so a junk row predating the guard can't absorb another tenant's URL.
- The ``cite-url`` derive funnel (``psl.root_host_from_url``) refuses to mint
  a site root on a shared host — a contributor paste can't create one.

This is a sibling of the deliverer table (``deliverers.py``), in the same
authoring discipline: entries are pure configuration, malformed declarations
fail at import, and matching reuses ``hosts.py``'s label-boundary suffix
vocabulary. It is deliberately neither a deliverer (those *forbid* identity —
a shared host's files are first-party evidence, just path-addressed) nor a
recognition row (those *are* identity — this table only constrains how they
may be declared).
"""

from __future__ import annotations

from typing import NamedTuple

from apps.citation.hosts import Host, is_dns_host, label_suffixes, normalize_host


class SharedHostSpec(NamedTuple):
    """One shared CDN's declared facts. Pure configuration — no behavior.

    - ``label``: user-facing platform name ("GoDaddy Website Builder CDN"),
      used in guard messages.
    - ``hosts``: normalized hosts the platform serves tenants on, matched by
      label-boundary suffix. Declare the **widest honest host**: suffix
      matching only looks up the label chain, so declaring a leaf
      (``img1.wsimg.com``) would leave its parent (``wsimg.com``) freely
      registrable — a bare ancestor row every leaf URL would then match.
      ``wsimg.com`` is declared whole because every subdomain is tenant CDN;
      ``cdn.shopify.com`` stays a leaf because ``shopify.com`` itself is a
      legitimate, non-shared site.
    """

    label: str
    hosts: tuple[str, ...]


SHARED_HOSTS: tuple[SharedHostSpec, ...] = (
    SharedHostSpec(label="GoDaddy Website Builder CDN", hosts=("wsimg.com",)),
    SharedHostSpec(label="Shopify CDN", hosts=("cdn.shopify.com",)),
    SharedHostSpec(label="Google Cloud Storage", hosts=("storage.googleapis.com",)),
    # Not a CDN, but the same recognition shape: every facebook.com URL is a
    # tenant's page, addressed by path (/<page-slug>), and a maker's own page
    # is first-party evidence. Declared whole — www./m. variants are label
    # suffixes of the registrable domain.
    SharedHostSpec(label="Facebook", hosts=("facebook.com",)),
)


def _validate_and_index(
    specs: tuple[SharedHostSpec, ...],
) -> dict[Host, SharedHostSpec]:
    """Index *specs* by host, validating every declaration at import.

    The deliverer table's fail-at-registration rule: an un-normalized or
    non-DNS host, a host claimed twice, or nested hosts (which would make
    match order matter) all fail the import, not the first recognition.
    """
    index: dict[Host, SharedHostSpec] = {}
    for spec in specs:
        for raw in spec.hosts:
            host = Host(raw)
            if normalize_host(raw) != raw or not is_dns_host(host):
                raise ValueError(
                    f"Shared host list for {spec.label!r} declares invalid host "
                    f"{raw!r}: hosts must be normalized DNS names."
                )
            if host in index:
                raise ValueError(
                    f"Shared host {raw!r} declared twice "
                    f"({index[host].label!r} and {spec.label!r})."
                )
            index[host] = spec
    for host in index:
        for suffix in label_suffixes(host)[1:]:
            if suffix in index:
                raise ValueError(
                    f"Shared host {host!r} nests under declared host "
                    f"{suffix!r}; declare only the outer host."
                )
    return index


_BY_HOST: dict[Host, SharedHostSpec] = _validate_and_index(SHARED_HOSTS)


def shared_host_for(host: Host) -> SharedHostSpec | None:
    """The shared-CDN spec owning *host*, by label-boundary suffix, or ``None``."""
    for suffix in label_suffixes(host):
        spec = _BY_HOST.get(suffix)
        if spec is not None:
            return spec
    return None
