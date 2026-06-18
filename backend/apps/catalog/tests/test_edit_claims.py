"""Tests for the domain spec-builders (edit_claims)."""

from __future__ import annotations

import pytest

from apps.catalog.api._typing import CreditKey, CreditPkKey
from apps.catalog.api.edit_claims import (
    _normalize_abbreviations,
    build_credit_claim_specs,
    build_gameplay_feature_claim_specs,
    build_m2m_claim_specs,
    normalize_credit_inputs,
    normalize_gameplay_feature_inputs,
)
from apps.catalog.exceptions import StructuredValidationError


class TestNormalizeGameplayFeatureInputs:
    def test_rejects_duplicate_slug(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_gameplay_feature_inputs([("ramps", 1), ("ramps", 2)])
        assert exc_info.value.field_errors == {
            "gameplay_features.ramps": "Duplicate feature.",
        }

    def test_rejects_non_positive_count(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_gameplay_feature_inputs([("ramps", 0)])
        assert exc_info.value.field_errors == {
            "gameplay_features.ramps": "Count must be positive, got 0.",
        }

    def test_rejects_unknown_slug_when_available_set_given(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_gameplay_feature_inputs(
                [("ramps", 2), ("loops", None)],
                available_slugs={"ramps"},
            )
        assert exc_info.value.field_errors == {
            "gameplay_features.loops": "Unknown gameplay feature.",
        }

    def test_accumulates_multiple_errors(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_gameplay_feature_inputs(
                [("ramps", 0), ("loops", -1)],
            )
        assert "gameplay_features.ramps" in exc_info.value.field_errors
        assert "gameplay_features.loops" in exc_info.value.field_errors

    def test_accepts_valid_input(self):
        desired = normalize_gameplay_feature_inputs(
            [("ramps", 2), ("loops", None)],
            available_slugs={"ramps", "loops"},
        )
        assert desired == {"ramps": 2, "loops": None}


class TestBuildGameplayFeatureClaimSpecs:
    def test_builds_add_and_remove_specs(self):
        specs = build_gameplay_feature_claim_specs(
            current={10: None},
            desired={20: 2},
        )
        by_key = {spec.claim_key: spec for spec in specs}
        assert set(by_key) == {
            "gameplay_feature|gameplay_feature:10",
            "gameplay_feature|gameplay_feature:20",
        }
        assert isinstance(by_key["gameplay_feature|gameplay_feature:20"].value, dict)
        assert isinstance(by_key["gameplay_feature|gameplay_feature:10"].value, dict)
        assert by_key["gameplay_feature|gameplay_feature:20"].value["count"] == 2
        assert by_key["gameplay_feature|gameplay_feature:10"].value["exists"] is False

    def test_skips_unchanged_specs(self):
        specs = build_gameplay_feature_claim_specs(
            current={20: 2},
            desired={20: 2},
        )
        assert specs == []


class TestNormalizeCreditInputs:
    def test_rejects_duplicate_pair(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_credit_inputs(
                [
                    CreditKey("pat-lawlor", "design"),
                    CreditKey("pat-lawlor", "design"),
                ]
            )
        assert exc_info.value.field_errors == {
            "credits.pat-lawlor:design": "Duplicate credit.",
        }

    def test_rejects_unknown_person(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_credit_inputs(
                [CreditKey("pat-lawlor", "design")],
                available_people={"john-youssi"},
                available_roles={"design"},
            )
        assert exc_info.value.field_errors == {
            "credits.pat-lawlor:design": "Unknown person: pat-lawlor.",
        }

    def test_rejects_unknown_role(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_credit_inputs(
                [CreditKey("pat-lawlor", "design")],
                available_people={"pat-lawlor"},
                available_roles={"software"},
            )
        assert exc_info.value.field_errors == {
            "credits.pat-lawlor:design": "Unknown role: design.",
        }

    def test_duplicate_error_not_clobbered_by_unknown_person(self):
        with pytest.raises(StructuredValidationError) as exc_info:
            normalize_credit_inputs(
                [
                    CreditKey("pat-lawlor", "design"),
                    CreditKey("pat-lawlor", "design"),
                ],
                available_people={"john-youssi"},
                available_roles={"design"},
            )
        assert exc_info.value.field_errors == {
            "credits.pat-lawlor:design": "Duplicate credit.",
        }

    def test_allows_same_person_with_different_roles(self):
        desired = normalize_credit_inputs(
            [
                CreditKey("pat-lawlor", "design"),
                CreditKey("pat-lawlor", "software"),
            ],
            available_people={"pat-lawlor"},
            available_roles={"design", "software"},
        )
        assert desired == {
            CreditKey("pat-lawlor", "design"),
            CreditKey("pat-lawlor", "software"),
        }


class TestBuildCreditClaimSpecs:
    def test_builds_add_and_remove_specs(self):
        specs = build_credit_claim_specs(
            current={CreditPkKey(100, 200)},
            desired={CreditPkKey(101, 201)},
        )
        by_key = {spec.claim_key: spec for spec in specs}
        assert set(by_key) == {
            "credit|person:100|role:200",
            "credit|person:101|role:201",
        }
        assert isinstance(by_key["credit|person:100|role:200"].value, dict)
        assert by_key["credit|person:100|role:200"].value["exists"] is False

    def test_skips_unchanged_specs(self):
        specs = build_credit_claim_specs(
            current={CreditPkKey(101, 201)},
            desired={CreditPkKey(101, 201)},
        )
        assert specs == []


class TestBuildM2MClaimSpecs:
    def test_builds_add_and_remove_specs(self):
        specs = build_m2m_claim_specs(
            current={1},
            desired={2},
            claim_field_name="theme",
        )
        by_key = {spec.claim_key: spec for spec in specs}
        assert set(by_key) == {
            "theme|theme:2",
            "theme|theme:1",
        }
        assert isinstance(by_key["theme|theme:1"].value, dict)
        assert by_key["theme|theme:1"].value["exists"] is False

    def test_skips_unchanged_specs(self):
        specs = build_m2m_claim_specs(
            current={1},
            desired={1},
            claim_field_name="theme",
        )
        assert specs == []


class TestNormalizeAbbreviations:
    def test_strips_blanks_and_deduplicates(self):
        assert _normalize_abbreviations([" MM ", "", "MM", "mm"]) == ["MM", "mm"]

    def test_rejects_too_long_values(self):
        with pytest.raises(StructuredValidationError, match="50 characters or fewer"):
            _normalize_abbreviations(["x" * 51])
