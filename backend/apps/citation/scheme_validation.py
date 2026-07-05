"""Semantic validation of the scheme registry — the Public-Suffix-List tier.

Structural coherence — every ``SourceType`` has a type spec, unique keys, a
scheme's owning type is registered, its declaration matches its type's
``scheme_spec_type``, and no two schemes share a URL-shape host — is enforced at
import in ``citation_types.registry._assert_registry_coherent``, which needs
nothing but the specs themselves.

This module is the second tier: the declaration checks that need the Public
Suffix List (a recognition host must be a real registrable domain, never a bare
public suffix that would over-match every site beneath it) and therefore cannot
live inside the deliberately PSL-free ``citation_types`` package. ``psl`` and
``hosts`` sit above ``citation_types`` in the import graph, so a validator that
consults them belongs here, in the app layer that may.

``validate_scheme`` is pure and spec-only — no driver, no example data, no DB —
so one implementation serves three callers: a Django system check
(``manage.py check`` at startup, on deploy and in CI), the conformance harness,
and — once schemes become UI-created rows rather than code — the creation
endpoint that must reject a malformed submission before it is stored.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from django.apps.config import AppConfig
from django.core.checks import CheckMessage, Error, Tags, register

from apps.citation.citation_types import SCHEME_SPECS, SchemeSpec
from apps.citation.hosts import is_dns_host, normalize_host
from apps.citation.psl import is_public_suffix


def validate_scheme(spec: SchemeSpec) -> list[str]:
    """Return *spec*'s declaration problems as human-readable strings, empty if valid.

    Each problem is prefixed with the scheme key so a registry-wide report
    reads unambiguously. Checks only what a pure spec can answer:

    - ``key`` is present and lowercase; ``label`` is present;
    - the platform root's ``name`` is present and its ``homepage_url`` is an
      https URL with a host;
    - every declared shape host and recognition host is a normalized DNS host,
      and no recognition host is a bare public suffix (which would over-match
      every unrelated site beneath it under longest-suffix recognition);
    - every recognition host is covered by a declared shape host (a recognition
      host matching no shape is a typo);
    - a scheme that extracts start-time hints (``start_seconds_source``) also
      declares a ``deep_link_template`` to honor them.
    """
    problems: list[str] = []

    if not spec.key or spec.key != spec.key.lower():
        problems.append(f"key {spec.key!r} must be non-empty and lowercase")
    if not spec.label:
        problems.append("label must be non-empty")

    info = spec.root_citation_source_info
    if not info.name:
        problems.append("root_citation_source_info.name must be non-empty")
    homepage = urlparse(info.homepage_url)
    if homepage.scheme != "https" or not homepage.hostname:
        problems.append(f"homepage_url {info.homepage_url!r} must be https with a host")

    shape_hosts = {host for shape in spec.url_shapes for host in shape.hosts}
    for host in sorted(shape_hosts):
        normalized = normalize_host(host)
        if host != normalized or not is_dns_host(normalized):
            problems.append(f"shape host {host!r} is not a normalized DNS host")

    for host in info.recognition_hosts:
        normalized = normalize_host(host)
        if host != normalized or not is_dns_host(normalized):
            problems.append(f"recognition host {host!r} is not a normalized DNS host")
        elif is_public_suffix(normalized):
            problems.append(f"recognition host {host!r} is a bare public suffix")
        elif not any(sh == host or sh.endswith(f".{host}") for sh in shape_hosts):
            problems.append(f"recognition host {host!r} matches no declared shape")

    if spec.start_seconds_source is not None and spec.deep_link_template is None:
        problems.append(
            "declares start_seconds_source but no deep_link_template to honor it"
        )

    return [f"{spec.key}: {problem}" for problem in problems]


def validate_registry() -> list[str]:
    """Every registered scheme's declaration problems, in registry order."""
    return [
        problem for spec in SCHEME_SPECS.values() for problem in validate_scheme(spec)
    ]


@register(Tags.models)
def check_citation_schemes(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401  # Django check-framework signature
) -> list[CheckMessage]:
    """Fail ``manage.py check`` if any registered scheme's declaration is malformed.

    The startup/deploy/CI surface for :func:`validate_registry`; the structural
    invariants already fail hard at import, so anything reaching here is a
    PSL-tier declaration problem worth a readable error rather than a traceback.
    """
    _ = app_configs, kwargs
    return [
        Error(problem, obj="citation schemes", id="citation.E001")
        for problem in validate_registry()
    ]
