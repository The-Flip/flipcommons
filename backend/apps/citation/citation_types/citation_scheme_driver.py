"""The citation-scheme framework: the shape compiler and the scheme driver.

**Framework-facing only** — a scheme author never imports, sees or
subclasses this module; an import-linter contract fails the build if a
plugin module tries. Everything the system *does* with a scheme's pure
declarations happens here or in the registry:

- The **shape compiler** turns declared :class:`UrlShape` rows into one
  anchored recognition pattern, applying the security-sensitive plumbing
  itself so an author cannot forget it: the host prefix is anchored on
  ``https?://`` and dot-escaped (a look-alike host can't match); the
  ``{id}`` capture is guarded against extension (a longer token never
  truncates back to a valid-looking id); a path shape must consume the
  whole path unless it opts into tolerated tails; a query id is read from
  the query only, and the parameter scan can't cross ``#`` into the
  fragment. The conformance harness re-checks the spoof and truncation
  invariants behaviorally, as a backstop on this compiler.
- :class:`SchemeDriver` wraps one :class:`SchemeSpec` record and owns every
  behavior the framework runs against it: compilation at registration, URL
  recognition, identifier validation/normalization and the URL builders.
  The registry constructs one driver per registered spec; behavior is never
  added to the spec classes themselves, and a conformance guard fails the
  build if it ever is.

The single shared implementation here is what guarantees every scheme
resolves input identically; the conformance harness exercises it against
every registered scheme.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeSpec,
    StartSecondsSource,
    UrlShape,
)
from apps.citation.citation_types.vocabulary import StartSeconds

# The id capture's extension guard: the captured id must not continue into a
# longer identifier-charset token.
_ID_EXTENSION_GUARD = r"(?![A-Za-z0-9_-])"
# A path shape's terminator: at most one trailing slash, then only a query, a
# fragment or the end — never more path.
_PATH_END = r"(?=/?(?:[?#]|$))"
# The tolerant variant for allow_path_tail: anything may follow a ``/``.
_TAIL_OK_END = r"(?=[/?#]|$)"

_ID_SLOT = "{id}"


def start_seconds_hint_values(source: StartSecondsSource, url: str) -> list[str]:
    """The raw string values *url* carries for *source*'s params, params-major.

    Framework plumbing for the registry's hint weave — not author surface. A
    URL too malformed for ``urlparse`` yields ``[]`` rather than raising.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return []
    text = parsed.query if source.location == "query" else parsed.fragment
    found = parse_qs(text)
    return [value for name in source.params for value in found.get(name, [])]


def _host_prefix(hosts: tuple[str, ...], subdomains: tuple[str, ...]) -> str:
    """The anchored, dot-escaped ``https?://<subdomain?><host>`` prefix.

    Only non-capturing groups are emitted, so each shape's id capture stays
    its branch's sole group — the driver reads the identifier by
    ``lastindex``.
    """
    hosts_alt = "|".join(re.escape(h) for h in hosts)
    if not subdomains:
        return rf"https?://(?:{hosts_alt})"
    prefix = "|".join(re.escape(s) + r"\." for s in subdomains)
    return rf"https?://(?:{prefix})?(?:{hosts_alt})"


def _compile_shape(shape: UrlShape, id_pattern: str) -> str:
    """One shape's full anchored regex source, id captured and bounded."""
    if not shape.hosts:
        raise ValueError("UrlShape needs at least one host")
    for host in shape.hosts:
        if host != host.lower() or "//" in host or "/" in host:
            raise ValueError(f"UrlShape host {host!r} must be a bare lowercase host")
    id_capture = f"({id_pattern}){_ID_EXTENSION_GUARD}"
    if shape.query_id_param:
        if _ID_SLOT in shape.path:
            raise ValueError("UrlShape takes an {id} slot or query_id_param, not both")
        # The parameter scan stays inside the query: it can't cross ``#``
        # into the fragment (or whitespace into surrounding text), and other
        # parameters may precede or follow the id.
        body = (
            shape.path
            + r"\?(?:[^\s#]*&)?"
            + re.escape(shape.query_id_param)
            + "="
            + id_capture
        )
    else:
        if shape.path.count(_ID_SLOT) != 1:
            raise ValueError(
                f"UrlShape path {shape.path!r} needs exactly one {{id}} slot "
                f"(or a query_id_param)"
            )
        end = _TAIL_OK_END if shape.allow_path_tail else _PATH_END
        body = shape.path.replace(_ID_SLOT, id_capture) + end
    return _host_prefix(shape.hosts, shape.subdomains) + body


def compile_url_shapes(
    shapes: tuple[UrlShape, ...], id_pattern: str
) -> re.Pattern[str]:
    """Compile a scheme's declared shapes into its one recognition pattern.

    ``id_pattern`` is the scheme's bare-identifier grammar; it must contain
    no capture groups of its own (the compiler adds the one capture per
    shape, and the driver reads it by ``lastindex``).
    """
    if not shapes:
        raise ValueError("A scheme must declare at least one UrlShape")
    if re.compile(id_pattern).groups:
        raise ValueError(f"id_pattern {id_pattern!r} must not contain capture groups")
    return re.compile(
        "(?:" + "|".join(_compile_shape(shape, id_pattern) for shape in shapes) + ")"
    )


class SchemeDriver:
    """Drives one scheme spec: compiled recognition plus the URL builders.

    Construction compiles the spec's declarations, so a malformed one (no
    ``{id}`` slot, capture groups in ``id_pattern``, a bad host) raises at
    registration — import time — not at first recognition.
    """

    def __init__(self, spec: SchemeSpec) -> None:
        self.spec = spec
        self._url_pattern = compile_url_shapes(spec.url_shapes, spec.id_pattern)
        self._id_pattern = re.compile(spec.id_pattern)

    def canonical_url(self, identifier: str) -> str:
        """The one URL every recognized shape of *identifier* collapses to."""
        return self.spec.canonical_url_template.format(identifier=identifier)

    def deep_link(self, identifier: str, start_seconds: StartSeconds) -> str | None:
        """The URL that jumps to *start_seconds* within *identifier*.

        ``None`` when the scheme declares no ``deep_link_template`` — the
        platform's URLs cannot seek.
        """
        if self.spec.deep_link_template is None:
            return None
        return self.spec.deep_link_template.format(
            identifier=identifier, start_seconds=start_seconds
        )

    def extract(self, url: str) -> str | None:
        """The identifier when *url* is one of the scheme's shapes, else ``None``."""
        m = self._url_pattern.search(url)
        if m is None:
            return None
        # Exactly one shape's alternation branch participates, so its capture
        # is the highest-numbered matched group.
        assert m.lastindex is not None, "url_pattern must capture the identifier"
        return m.group(m.lastindex)

    def validate_identifier(self, raw: str) -> str | None:
        """Return *raw* when it is a well-formed bare identifier, else ``None``."""
        return raw if self._id_pattern.fullmatch(raw) else None

    def normalize(self, raw: str) -> str | None:
        """Extract a valid identifier from a URL or bare value, or ``None``.

        Tries the URL shapes first, then validates as a bare identifier.
        """
        identifier = self.extract(raw)
        if identifier is not None:
            return identifier
        return self.validate_identifier(raw)
