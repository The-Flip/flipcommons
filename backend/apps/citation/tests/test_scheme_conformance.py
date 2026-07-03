"""The scheme conformance harness.

Parametrized over the scheme registry, so **every registered scheme passes
through automatically** — a new scheme enrolls just by being registered, and
a third-party module is held to the ``SchemeSpec`` contract without its
author knowing the house rules. Scheme-specific behavior (a platform's real
URL shapes) still belongs in that scheme's own example-based tests; this
harness checks only the invariants shared code relies on.

Pure — no database. See ``docs/plans/citations/VideoCitations.md``.
"""

from urllib.parse import urlparse

import pytest

from apps.citation.citation_types import SCHEME_SPECS, SchemeSpec
from apps.citation.hosts import is_dns_host, normalize_host
from apps.citation.psl import is_public_suffix

# Junk no scheme's identifier grammar should accept. Deliberately generic —
# per-scheme wrongness (a 12-char YouTube id) lives in the scheme's own tests.
JUNK_IDENTIFIERS = ["", " ", "has space", "new\nline", "!!!", "a/b?c=d"]


# Parametrized by key (not spec object) so test ids read as the scheme names
# and the fixture's return stays typed through the mapping lookup.
@pytest.fixture(params=list(SCHEME_SPECS))
def spec(request: pytest.FixtureRequest) -> SchemeSpec:
    return SCHEME_SPECS[request.param]


class TestSchemeConformance:
    def test_canonical_url_round_trips_through_extract(self, spec):
        """The canonical URL is one of the scheme's own recognized shapes."""
        url = spec.canonical_url(spec.example_identifier)
        match = spec.extract(url)
        assert match is not None, f"{spec.key}: canonical URL not recognized: {url}"
        assert match.identifier == spec.example_identifier

    def test_example_identifier_is_valid_bare(self, spec):
        assert spec.validate_identifier(spec.example_identifier) == (
            spec.example_identifier
        )

    def test_normalize_accepts_url_and_bare_forms(self, spec):
        url = spec.canonical_url(spec.example_identifier)
        assert spec.normalize(url) == spec.example_identifier
        assert spec.normalize(spec.example_identifier) == spec.example_identifier

    @pytest.mark.parametrize("junk", JUNK_IDENTIFIERS)
    def test_junk_identifiers_are_rejected(self, spec, junk):
        assert spec.validate_identifier(junk) is None

    def test_url_pattern_is_host_anchored(self, spec):
        """A look-alike host must not match (``notyoutube.com`` spoof).

        Prefixing the canonical host with a label fragment must break
        recognition — the pattern anchors on ``https?://<host>``, not on the
        host appearing anywhere in the URL.
        """
        url = spec.canonical_url(spec.example_identifier)
        host = urlparse(url).hostname
        assert host, f"{spec.key}: canonical URL has no host: {url}"
        spoofed = url.replace(f"://{host}", f"://not{host}", 1)
        assert spec.extract(spoofed) is None, f"{spec.key}: matched {spoofed}"

    def test_canonical_url_is_https_on_a_real_host(self, spec):
        url = spec.canonical_url(spec.example_identifier)
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.hostname
        assert is_dns_host(normalize_host(parsed.hostname))

    def test_extract_never_returns_locator_text(self, spec):
        """A scheme hint is a structured value, never a preformatted string.

        ``start_seconds`` is ``int | None`` by contract; this pins the runtime
        shape for schemes whose ``extract`` is hand-written.
        """
        match = spec.extract(spec.canonical_url(spec.example_identifier))
        assert match is not None
        assert match.start_seconds is None or isinstance(match.start_seconds, int)

    def test_root_seed_is_well_formed(self, spec):
        seed = spec.root_seed
        assert seed.name, f"{spec.key}: root_seed.name is blank"
        parsed = urlparse(seed.homepage_url)
        assert parsed.scheme == "https", f"{spec.key}: homepage_url is not https"
        assert parsed.hostname, f"{spec.key}: homepage_url has no host"
        for host in seed.recognition_hosts:
            assert host == normalize_host(host), (
                f"{spec.key}: recognition host {host!r} is not normalized"
            )
            assert is_dns_host(host), f"{spec.key}: bad recognition host {host!r}"
            assert not is_public_suffix(host), (
                f"{spec.key}: recognition host {host!r} is a bare public suffix"
            )

    def test_key_and_label_are_present(self, spec):
        assert spec.key
        assert spec.key == spec.key.lower()
        assert spec.label
