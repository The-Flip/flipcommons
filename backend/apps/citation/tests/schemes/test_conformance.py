"""The scheme conformance harness.

Parametrized over the scheme registry, so **every registered scheme passes
through automatically** — a new scheme enrolls just by being registered, and
a third-party declaration is held to the contract without its author knowing
the house rules. Behavior is exercised through the framework's
``SchemeDriver`` (authors declare, the framework drives); the declarations
themselves are held to the pure-data rule by the no-logic guard and the JSON
round-trip proof. Scheme-specific behavior (a platform's real URL shapes)
still belongs in that scheme's own example tables; this harness checks only
the invariants shared code relies on.

Pure — no database. See ``docs/plans/citations/CitationPluginSystem.md``.
"""

import dataclasses
import json
from urllib.parse import urlparse

import pytest

from apps.citation.citation_types import (
    SCHEME_DRIVERS,
    SCHEME_SPECS,
    SchemeDriver,
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    SourceType,
    StartSecondsSource,
    UrlShape,
    citation_type_spec,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.hosts import is_dns_host, normalize_host
from apps.citation.psl import is_public_suffix

from .example_registry import SCHEME_EXAMPLES


@pytest.mark.parametrize(
    "declaration_cls",
    [
        SchemeSpec,
        VideoSchemeSpec,
        UrlShape,
        StartSecondsSource,
        SchemeRootCitationSourceInfo,
    ],
)
def test_author_declaration_classes_carry_no_logic(declaration_cls: type) -> None:
    """The types a scheme author instantiates are pure data — fields only.

    Python cannot statically forbid methods on a dataclass, so this guard
    makes the rule build-failing instead: framework behavior belongs on the
    framework side of the module wall (``citation_scheme_driver``, the
    registry weaves), never on the declaration values an author fills in.
    """
    offenders = [
        name
        for name, value in vars(declaration_cls).items()
        if not name.startswith("__")
        and (callable(value) or isinstance(value, property))
    ]
    assert offenders == [], (
        f"{declaration_cls.__name__} declares logic ({offenders}); "
        f"author declaration types must be pure data"
    )


# Junk no scheme's identifier grammar should accept. Deliberately generic —
# per-scheme wrongness (a 12-char YouTube id) lives in the scheme's own tests.
JUNK_IDENTIFIERS = ["", " ", "has space", "new\nline", "!!!", "a/b?c=d"]


# Parametrized by key (not spec object) so test ids read as the scheme names
# and the fixtures' returns stay typed through the mapping lookups.
@pytest.fixture(params=list(SCHEME_SPECS))
def spec(request: pytest.FixtureRequest) -> SchemeSpec:
    return SCHEME_SPECS[request.param]


@pytest.fixture
def driver(spec: SchemeSpec) -> SchemeDriver:
    """The framework's driver for the spec under test — behavior runs here."""
    return SCHEME_DRIVERS[spec.key]


@pytest.fixture
def example_id(spec: SchemeSpec) -> str:
    """The scheme's round-trip seed — one known-good identifier, from its
    test-side example table rather than the production spec."""
    return SCHEME_EXAMPLES[spec.key].example_identifier


class TestSchemeConformance:
    def test_spec_round_trips_through_json(self, spec):
        """A registered scheme is provably pure data: it survives JSON.

        ``json.dumps`` physically rejects callables, compiled patterns and
        any other live object, so a scheme that smuggles code in a field
        cannot pass; rebuilding the spec from the parsed document and
        comparing equal proves the declaration is fully expressible as a
        stored row (the Stream G3 shape).
        """
        data = json.loads(json.dumps(dataclasses.asdict(spec)))
        rebuilt = type(spec)(
            key=data["key"],
            label=data["label"],
            source_type=SourceType(data["source_type"]),
            url_shapes=tuple(
                UrlShape(
                    hosts=tuple(shape["hosts"]),
                    path=shape["path"],
                    subdomains=tuple(shape["subdomains"]),
                    query_id_param=shape["query_id_param"],
                    allow_path_tail=shape["allow_path_tail"],
                )
                for shape in data["url_shapes"]
            ),
            id_pattern=data["id_pattern"],
            canonical_url_template=data["canonical_url_template"],
            root_citation_source_info=SchemeRootCitationSourceInfo(
                name=data["root_citation_source_info"]["name"],
                homepage_url=data["root_citation_source_info"]["homepage_url"],
                recognition_hosts=tuple(
                    data["root_citation_source_info"]["recognition_hosts"]
                ),
            ),
            deep_link_template=data["deep_link_template"],
            start_seconds_source=(
                StartSecondsSource(
                    location=data["start_seconds_source"]["location"],
                    params=tuple(data["start_seconds_source"]["params"]),
                )
                if data["start_seconds_source"] is not None
                else None
            ),
        )
        assert rebuilt == spec

    def test_canonical_url_round_trips_through_extract(self, driver, example_id):
        """The canonical URL is one of the scheme's own recognized shapes."""
        url = driver.canonical_url(example_id)
        assert driver.extract(url) == example_id, (
            f"{driver.spec.key}: canonical URL not recognized: {url}"
        )

    def test_example_identifier_is_valid_bare(self, driver, example_id):
        assert driver.validate_identifier(example_id) == example_id

    def test_normalize_accepts_url_and_bare_forms(self, driver, example_id):
        url = driver.canonical_url(example_id)
        assert driver.normalize(url) == example_id
        assert driver.normalize(example_id) == example_id

    @pytest.mark.parametrize("junk", JUNK_IDENTIFIERS)
    def test_junk_identifiers_are_rejected(self, driver, junk):
        assert driver.validate_identifier(junk) is None

    @pytest.mark.parametrize("junk_char", ["a", "9", "-"])
    def test_extended_identifier_never_truncates_back(
        self, driver, example_id, junk_char
    ):
        """A corrupted identifier must not round-trip to the clean one.

        Append an id-charset-plausible character to the identifier inside the
        canonical URL: extraction may reject it or read a *different* id, but
        must never truncate back to the real one — otherwise a mangled paste
        silently mints or dedups to the wrong child. The shape compiler's
        id-extension guard makes this unwritable; this test is the
        behavioral backstop on the compiler itself.
        """
        url = driver.canonical_url(example_id + junk_char)
        assert driver.extract(url) != example_id, f"{driver.spec.key}: truncated {url}"

    def test_url_pattern_is_host_anchored(self, driver, example_id):
        """A look-alike host must not match (``notyoutube.com`` spoof).

        Prefixing the canonical host with a label fragment must break
        recognition — the compiler anchors on ``https?://<host>``, not on the
        host appearing anywhere in the URL; this is its behavioral backstop.
        """
        url = driver.canonical_url(example_id)
        host = urlparse(url).hostname
        assert host, f"{driver.spec.key}: canonical URL has no host: {url}"
        spoofed = url.replace(f"://{host}", f"://not{host}", 1)
        assert driver.extract(spoofed) is None, f"{driver.spec.key}: matched {spoofed}"

    def test_canonical_url_is_https_on_a_real_host(self, driver, example_id):
        url = driver.canonical_url(example_id)
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.hostname
        assert is_dns_host(normalize_host(parsed.hostname))

    def test_recognition_hosts_are_covered_by_declared_shapes(self, spec):
        """Every recognition host is one of the scheme's shape hosts.

        The two host sets are declared separately (a recognition host may
        also cover shape hosts that are its subdomains, and a redirect-style
        shape host like ``youtu.be`` is deliberately *not* a recognition
        host), but a recognition host matching none of the shapes is a typo.
        """
        shape_hosts = {h for shape in spec.url_shapes for h in shape.hosts}
        for rh in spec.root_citation_source_info.recognition_hosts:
            assert any(sh == rh or sh.endswith("." + rh) for sh in shape_hosts), (
                f"{spec.key}: recognition host {rh!r} matches no declared shape"
            )

    def test_root_citation_source_info_is_well_formed(self, spec):
        info = spec.root_citation_source_info
        assert info.name, f"{spec.key}: root_citation_source_info.name is blank"
        parsed = urlparse(info.homepage_url)
        assert parsed.scheme == "https", f"{spec.key}: homepage_url is not https"
        assert parsed.hostname, f"{spec.key}: homepage_url has no host"
        for host in info.recognition_hosts:
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

    def test_scheme_implements_its_types_contract(self, spec):
        assert isinstance(spec, citation_type_spec(spec.source_type).scheme_spec_type)

    def test_start_seconds_extraction_implies_deep_link(self, spec):
        """A scheme that reads seek positions from URLs must also build them.

        ``deep_link_template`` is optional overall — some platforms' URLs
        cannot seek (TikTok) and their citations degrade to locator text
        beside the plain canonical link. But a scheme whose URLs *carry*
        start times has proven the platform can jump, so declaring a
        ``start_seconds_source`` without a ``deep_link_template`` would
        collect locators it then never honors at read time.
        """
        if spec.start_seconds_source is not None:
            assert spec.deep_link_template is not None, (
                f"{spec.key}: extracts start-time hints but has no deep-link "
                f"template to honor them"
            )

    def test_deep_link_output_is_well_formed_on_the_schemes_host(
        self, spec, driver, example_id
    ):
        if spec.deep_link_template is None:
            pytest.skip("scheme has no deep_link_template")
        canonical_host = urlparse(driver.canonical_url(example_id)).hostname
        for seconds in (0, 95, 3723):
            url = driver.deep_link(example_id, seconds)
            assert url is not None
            parsed = urlparse(url)
            assert parsed.scheme == "https"
            assert parsed.hostname == canonical_host, (
                f"{spec.key}: deep link left the scheme's host: {url}"
            )

    def test_start_seconds_hint_round_trips_the_type_grammar(self, spec):
        """A scheme's structured hint must be expressible as locator text.

        Recognition may surface ``start_seconds``; the owning type formats it
        to prefill the locator stage, and that text must re-parse to the same
        value — otherwise the prefill would fail the type's own validation.
        """
        if spec.start_seconds_source is None:
            pytest.skip("scheme extracts no start-time hints")
        contract = citation_type_spec(spec.source_type).locator
        assert contract.format_value is not None
        assert contract.parse_value is not None
        for seconds in (1, 95, 3723):
            assert contract.parse_value(contract.format_value(seconds)) == seconds
