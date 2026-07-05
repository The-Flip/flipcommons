"""Tests for the citation-type/scheme registry (``apps.citation.citation_types``).

Pure data plus a coercing accessor and coherence assertions — no database.
The per-scheme behavioral contract is covered separately by
``schemes/test_conformance.py``.
"""

import dataclasses

import pytest

from apps.citation.citation_types import (
    CITATION_TYPE_SPECS,
    SCHEME_SPECS,
    SourceType,
    UrlShape,
    citation_type_spec,
    identifier_key_choices,
    identifier_key_values,
    is_known_scheme,
    known_scheme_keys,
    normalize_scheme_identifier,
    recognize_scheme,
    scheme_bindings,
    scheme_canonical_url,
    scheme_deep_link,
    scheme_root_citation_source_info,
    scheme_source_type,
)
from apps.citation.citation_types.registry import (
    _assert_registry_coherent,
    _discover_scheme_specs,
)


class TestCitationTypeSpecs:
    @pytest.mark.parametrize(
        ("source_type", "flat", "abstract", "skips_locator"),
        [
            (SourceType.BOOK, False, False, False),
            (SourceType.MAGAZINE, False, True, False),
            (SourceType.WEB, True, True, True),
        ],
    )
    def test_traits_per_type(self, source_type, flat, abstract, skips_locator):
        spec = citation_type_spec(source_type)
        assert spec.flat_hierarchy is flat
        assert spec.parentless_abstract is abstract
        assert spec.child_skips_locator is skips_locator

    def test_accessor_coerces_a_raw_field_string(self):
        # A model's ``source_type`` CharField arrives as a plain ``str``.
        assert citation_type_spec("web") == CITATION_TYPE_SPECS[SourceType.WEB]

    def test_accessor_rejects_an_unknown_value(self):
        with pytest.raises(ValueError, match="not a valid SourceType"):
            citation_type_spec("podcast")

    def test_label_comes_from_the_choice(self):
        assert citation_type_spec("web").source_type.label == "Web"


class TestSchemeRegistry:
    def test_identifier_key_values_are_the_scheme_keys(self):
        assert identifier_key_values() == list(SCHEME_SPECS)

    def test_identifier_key_choices_pair_key_and_label(self):
        assert identifier_key_choices() == [
            (spec.key, spec.label) for spec in SCHEME_SPECS.values()
        ]

    def test_mapping_keys_match_spec_keys(self):
        for key, spec in SCHEME_SPECS.items():
            assert key == spec.key

    def test_schemes_are_auto_discovered_in_key_order(self):
        assert list(SCHEME_SPECS.values()) == list(_discover_scheme_specs())
        assert list(SCHEME_SPECS) == sorted(SCHEME_SPECS)

    def test_scheme_bindings_bind_key_to_owning_type(self):
        bindings = scheme_bindings()
        assert bindings == [
            (spec.key, spec.source_type) for spec in SCHEME_SPECS.values()
        ]
        # Named fields, not positional guessing — the point of the NamedTuple.
        youtube = next(
            binding for binding in bindings if binding.identifier_key == "youtube"
        )
        assert youtube.source_type is SourceType.VIDEO


class TestExternalCustomerAccessors:
    """The pure scheme queries customers call instead of reading spec fields."""

    def test_recognize_scheme_yields_key_label_and_identifier(self):
        rec = recognize_scheme("https://www.ipdb.org/machine.cgi?id=4443")
        assert rec is not None
        assert rec.scheme == "ipdb"
        assert rec.label == "IPDB"
        assert rec.identifier == "4443"
        assert rec.start_seconds is None

    def test_recognize_scheme_carries_the_start_time_hint(self):
        rec = recognize_scheme("https://youtu.be/dQw4w9WgXcQ?t=95")
        assert rec is not None
        assert rec.scheme == "youtube"
        assert rec.start_seconds == 95

    def test_recognize_scheme_abstains_on_an_unrecognized_url(self):
        assert recognize_scheme("https://example.com/article") is None

    def test_known_scheme_keys_and_membership(self):
        assert known_scheme_keys() == list(SCHEME_SPECS)
        assert is_known_scheme("youtube")
        assert not is_known_scheme("betamax")

    def test_scheme_source_type_is_the_owning_type(self):
        assert scheme_source_type("youtube") is SourceType.VIDEO
        assert scheme_source_type("x") is SourceType.WEB

    def test_scheme_source_type_rejects_an_unknown_key(self):
        with pytest.raises(ValueError, match="Unknown scheme"):
            scheme_source_type("betamax")

    def test_normalize_scheme_identifier_accepts_url_and_bare_forms(self):
        assert normalize_scheme_identifier("ipdb", "4443") == "4443"
        url = "https://www.ipdb.org/machine.cgi?id=4443"
        assert normalize_scheme_identifier("ipdb", url) == "4443"
        assert normalize_scheme_identifier("ipdb", "not-a-number") is None

    def test_normalize_scheme_identifier_rejects_an_unknown_key(self):
        with pytest.raises(ValueError, match="Unknown scheme"):
            normalize_scheme_identifier("betamax", "4443")

    def test_scheme_root_citation_source_info_returns_facts_or_none(self):
        info = scheme_root_citation_source_info("youtube")
        assert info is not None
        assert info.name == "YouTube"
        # None, not ValueError: ingest validation queries with a
        # patch-declared key before the field validator reports it.
        assert scheme_root_citation_source_info("betamax") is None

    def test_scheme_canonical_url_builds_the_collapse_target(self):
        url = scheme_canonical_url("ipdb", "4443")
        assert url == "https://www.ipdb.org/machine.cgi?id=4443"
        with pytest.raises(ValueError, match="Unknown scheme"):
            scheme_canonical_url("betamax", "4443")

    def test_scheme_deep_link_weaves_type_grammar_into_scheme_url(self):
        # The composition contract: "1:02:03" is parsed by the video *type*,
        # the youtube *scheme* renders the resulting seconds as a seek URL.
        url = scheme_deep_link("youtube", "dQw4w9WgXcQ", "1:02:03")
        assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3723s"

    def test_scheme_deep_link_declines_when_a_layer_declines(self):
        # No deep_link builder (TikTok can't seek), no structured locator
        # value (web is freeform), or an unparseable locator.
        assert scheme_deep_link("tiktok", "user/video/1", "1:35") is None
        assert scheme_deep_link("ipdb", "4443", "p. 42") is None
        assert scheme_deep_link("youtube", "dQw4w9WgXcQ", "not a time") is None


class TestCoherenceHelper:
    def test_passes_on_the_real_registry(self):
        _assert_registry_coherent(
            CITATION_TYPE_SPECS, tuple(SCHEME_SPECS.values())
        )  # does not raise

    def test_raises_on_a_missing_type(self):
        incomplete = {SourceType.BOOK: CITATION_TYPE_SPECS[SourceType.BOOK]}
        with pytest.raises(AssertionError, match="missing a type spec"):
            _assert_registry_coherent(incomplete, tuple(SCHEME_SPECS.values()))

    def test_raises_on_overlapping_recognition_hosts(self):
        """Two schemes claiming one host would make recognition order-dependent."""
        youtube = SCHEME_SPECS["youtube"]
        clash = dataclasses.replace(
            youtube,
            key="clash",
            url_shapes=(UrlShape(hosts=("youtube.com",), path="/x/{id}"),),
        )
        with pytest.raises(AssertionError, match="share URL-shape hosts"):
            _assert_registry_coherent(CITATION_TYPE_SPECS, (youtube, clash))
