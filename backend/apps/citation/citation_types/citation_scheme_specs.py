"""The citation-scheme author's declarations — pure data, nothing else.

**This module is the entire authoring surface for a citation scheme**, the
third-party plugin unit (ipdb, opdb, youtube, vimeo, tiktok, x). Every class
here is a declaration a scheme author fills in: fields only, no methods, no
I/O. A scheme author sees this module and their owning type's spec subclass
(e.g. ``video.VideoSchemeSpec``) — never the framework that drives the
declarations (``citation_scheme_driver``, ``registry``) and never citation
*type* authoring (``citation_type_specs``); import-linter contracts enforce
both exclusions, a conformance guard fails the build if logic is ever added
to a class here, and a JSON round-trip test proves every registered scheme
is expressible as a plain document.

The one rule binding a scheme to its owning type — the **composition
contract**: the type owns locator semantics; a scheme speaks only structured
values. A video scheme declares where a start time rides in a URL and how a
seek URL is templated — never how ``1:02:03`` parses. The weaves live in the
registry.

A model-free leaf: imports only the shared ``vocabulary``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from apps.citation.citation_types.vocabulary import SchemeKey, SourceType


@dataclass(frozen=True, slots=True)
class SchemeRootCitationSourceInfo:
    """Declarative facts about a scheme's platform root ``CitationSource``.

    The root row is still created by a data patch — a scheme is live only once
    its root is seeded — but the patch is authored from these facts, and the
    ingest validation (``_validate_scheme_root_citation_source_info`` in
    ``source_upsert``) rejects a ``sources:`` declaration that disagrees with
    them, so the registry stays operationally authoritative.
    ``recognition_hosts`` are the ``CitationSourceRootDomain`` hosts the root
    should own (normalized: lowercase, no ``www.``).
    """

    name: str
    homepage_url: str
    recognition_hosts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UrlShape:
    """One recognized URL shape: hosts + where the identifier sits.

    - ``hosts``: the apex hosts this shape matches, bare and lowercase
      (``"youtube.com"``); the framework escapes and anchors them.
    - ``subdomains``: optional leading labels (default an optional ``www.``);
      pass ``()`` for a host that takes none (``player.vimeo.com``).
    - ``path``: a regex over the URL path, containing exactly one ``{id}``
      slot where the identifier sits (``"/machines/{id}"``) — the framework
      substitutes the scheme's id grammar, captures it and bounds it. For a
      query-carried id, ``path`` instead matches the path only
      (``"/watch"``) and names the parameter via ``query_id_param``.
    - ``query_id_param``: the query parameter whose value is the identifier
      (YouTube's ``v``, IPDB's ``id``). Mutually exclusive with an ``{id}``
      slot in ``path``.
    - ``allow_path_tail``: tolerate extra path segments after the shape
      (X's ``/status/<id>/photo/1``). Default strict: the shape must consume
      the whole path.
    """

    hosts: tuple[str, ...]
    path: str
    subdomains: tuple[str, ...] = ("www",)
    query_id_param: str = ""
    allow_path_tail: bool = False


@dataclass(frozen=True, slots=True)
class StartSecondsSource:
    """Where a platform's URLs carry a start-time hint — declarative, no code.

    A scheme declares only the *location*: named parameters read from the URL
    query (YouTube's ``?t=``/``?start=``) or fragment (Vimeo's ``#t=``).
    Reading them out of a URL is the framework's job, and parsing them is the
    owning type's (its locator value grammar, woven in the registry) — this
    class is pure data and never sees a URL.
    """

    location: Literal["query", "fragment"]
    params: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchemeSpec:
    """One platform's identifier scheme, as the author declares it.

    The third-party plugin unit, and **pure configuration**: fields only, no
    methods — a scheme declares facts and carries no code, which is what
    makes its capabilities bounded and (eventually) plausible as UI-built,
    DB-stored rows. The framework side of the wall
    (``citation_scheme_driver.SchemeDriver``) compiles and runs these
    declarations; an author never touches it. The scheme's whole surface is
    three declarations plus bookkeeping:

    - ``url_shapes``: the recognized URL shapes (:class:`UrlShape` — hosts
      plus a path pattern with an ``{id}`` slot, or a query parameter
      carrying the id). The framework compiles them into one anchored
      pattern, applying host escaping/anchoring and the identifier
      boundaries itself — an author cannot write a spoofable or truncating
      pattern.
    - ``id_pattern``: the bare-identifier grammar (a regex source string,
      no capture groups); fullmatched against typed-in identifiers and
      substituted into each shape's ``{id}`` slot.
    - ``canonical_url_template`` is a ``str.format`` template with exactly one
      placeholder, ``{identifier}``, building the one URL every shape
      collapses to — extracting from the built canonical URL must round-trip.
      Template substitution suffices by construction: the recognition
      contract already requires the identifier to be one contiguous substring
      of the URL (TikTok's composite ``user/video/id`` identity is designed
      around it).

    The two optional capabilities speak the owning type's structured locator
    value, never locator text:

    - ``deep_link_template`` adds ``{start_seconds}`` to the placeholders and
      builds the URL that jumps to a structured position (video: the watch
      URL with ``t=``). Optional even on value-carrying types — some
      platforms' URLs simply cannot seek (TikTok); their citations render the
      locator text beside the plain canonical link.
    - ``start_seconds_source`` declares where a recognized URL carries the
      structured position hint (``?t=95``). The values are parsed
      framework-side, in the registry, through the owning type's value
      grammar — this class never sees them. A scheme declaring this must also
      provide ``deep_link_template`` (conformance-enforced): URLs that carry
      seek positions prove the platform can jump.
    """

    key: SchemeKey
    label: str
    source_type: SourceType
    url_shapes: tuple[UrlShape, ...]
    id_pattern: str
    canonical_url_template: str
    root_citation_source_info: SchemeRootCitationSourceInfo
    deep_link_template: str | None = None
    start_seconds_source: StartSecondsSource | None = None
