"""Tests for the PSL-tier scheme validator and its system check.

Pure — no database. The structural coherence tier (unique keys, disjoint hosts,
type-contract) is covered by ``test_citation_type_registry``; this covers the
declaration checks that need the Public Suffix List.
"""

import dataclasses

from apps.citation.citation_types import SCHEME_SPECS
from apps.citation.scheme_validation import (
    check_citation_schemes,
    validate_registry,
    validate_scheme,
)


class TestRealRegistry:
    def test_every_registered_scheme_is_valid(self):
        for spec in SCHEME_SPECS.values():
            assert validate_scheme(spec) == []

    def test_validate_registry_is_clean(self):
        assert validate_registry() == []

    def test_system_check_passes(self):
        assert check_citation_schemes(app_configs=None) == []


class TestValidateScheme:
    def test_flags_bare_public_suffix_recognition_host(self):
        base = SCHEME_SPECS["ipdb"]
        broken = dataclasses.replace(
            base,
            root_citation_source_info=dataclasses.replace(
                base.root_citation_source_info, recognition_hosts=("co.uk",)
            ),
        )
        assert any("public suffix" in problem for problem in validate_scheme(broken))

    def test_flags_recognition_host_matching_no_shape(self):
        base = SCHEME_SPECS["ipdb"]
        broken = dataclasses.replace(
            base,
            root_citation_source_info=dataclasses.replace(
                base.root_citation_source_info, recognition_hosts=("example.org",)
            ),
        )
        assert any("matches no declared shape" in p for p in validate_scheme(broken))

    def test_flags_start_seconds_without_deep_link(self):
        broken = dataclasses.replace(SCHEME_SPECS["youtube"], deep_link_template=None)
        assert any("deep_link_template" in p for p in validate_scheme(broken))
