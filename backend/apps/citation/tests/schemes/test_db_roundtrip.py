"""DB round-trip conformance: every scheme through the core write paths.

Parametrized over the registry like ``test_conformance``, but DB-backed: seed
the scheme's root, mint a child, re-recognize and reuse it, and weave (or
decline) the deep link. Every registered scheme earns this integration
coverage just by being registered — the composite-identifier and no-seek
stress cases (TikTok) are exercised without any scheme naming this module.
"""

import pytest

from apps.accounts.test_factories import default_actor
from apps.citation.citation_types import (
    SCHEME_SPECS,
    SchemeSpec,
    citation_source_type,
    citation_type_spec,
)
from apps.citation.deep_links import deep_linked_url
from apps.citation.extractors import get_or_create_scheme_child, recognize_url
from apps.citation.models import CitationSource
from apps.citation.test_factories import identifier_key_value, make_citation_source

from .example_registry import SCHEME_EXAMPLES


@pytest.fixture(params=list(SCHEME_SPECS))
def spec(request: pytest.FixtureRequest) -> SchemeSpec:
    return SCHEME_SPECS[request.param]


@pytest.fixture
def root(spec: SchemeSpec, db: None) -> CitationSource:
    """The scheme's seeded platform root, built from its declared facts."""
    return make_citation_source(
        name=spec.root_citation_source_info.name,
        source_type=citation_source_type(spec.source_type),
        identifier_key=identifier_key_value(spec.key),
    )


class TestSchemeDbRoundTrip:
    def test_minting_from_an_alternate_shape_collapses_to_the_child(
        self, spec: SchemeSpec, root: CitationSource
    ) -> None:
        """A non-canonical URL shape mints the one canonical child."""
        ex = SCHEME_EXAMPLES[spec.key]
        url = ex.valid_urls[0] if ex.valid_urls else ex.canonical_url
        child = get_or_create_scheme_child(root, url, created_by=default_actor())
        assert child.identifier == ex.example_identifier
        assert child.source_type == spec.source_type
        assert child.name == f"{root.name} #{ex.example_identifier}"
        assert child.links.get().url == ex.canonical_url

    def test_recognition_resolves_the_url_and_reuses_the_child(
        self, spec: SchemeSpec, root: CitationSource
    ) -> None:
        ex = SCHEME_EXAMPLES[spec.key]
        child = get_or_create_scheme_child(
            root, ex.example_identifier, created_by=default_actor()
        )
        rec = recognize_url(ex.valid_urls[0] if ex.valid_urls else ex.canonical_url)
        assert rec is not None
        assert rec.child is not None
        assert rec.child.id == child.id
        assert rec.identifier == ex.example_identifier

    def test_deep_link_weaves_the_locator_or_leaves_the_url_untouched(
        self, spec: SchemeSpec, root: CitationSource
    ) -> None:
        """The composition contract end-to-end: the type parses locator text
        to its structured value, the scheme builds the jump URL from it — and
        when either layer declines (no ``deep_link`` builder, no structured
        locator value), the canonical URL passes through untouched and the
        locator text renders beside it."""
        ex = SCHEME_EXAMPLES[spec.key]
        child = get_or_create_scheme_child(
            root, ex.example_identifier, created_by=default_actor()
        )
        contract = citation_type_spec(child.source_type).locator
        if spec.deep_link_template is None or contract.format_value is None:
            # "1:35" parses on a value-carrying type (TikTok: no builder) and
            # is freeform noise on the rest — the URL must survive either way.
            assert deep_linked_url(child, "1:35", ex.canonical_url) == ex.canonical_url
        else:
            case = ex.deep_link_case
            assert case is not None  # the example harness enforces the pairing
            locator = contract.format_value(case.seconds)
            assert deep_linked_url(child, locator, ex.canonical_url) == case.url
