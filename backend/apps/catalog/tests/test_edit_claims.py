"""Tests for shared claim-edit helpers."""

from __future__ import annotations

import pytest

from apps.catalog.api._typing import CreditKey, CreditPkKey
from apps.catalog.api.edit_claims import (
    FieldConstraintSchema,
    _normalize_abbreviations,
    build_credit_claim_specs,
    build_gameplay_feature_claim_specs,
    build_m2m_claim_specs,
    get_field_constraints,
    normalize_credit_inputs,
    normalize_gameplay_feature_inputs,
    plan_scalar_field_claims,
    validate_scalar_fields,
)
from apps.catalog.exceptions import StructuredValidationError
from apps.catalog.models import CorporateEntity, MachineModel, Person, Title


class TestValidateScalarFields:
    def test_allows_clearing_nullable_and_blankable_fields(self):
        specs = validate_scalar_fields(
            Title,
            {
                "description": None,
                "franchise": None,
            },
        )

        assert {spec.field_name: spec.value for spec in specs} == {
            "description": "",
            "franchise": "",
        }

    def test_rejects_clearing_required_string_fields(self):
        with pytest.raises(StructuredValidationError, match="cannot be cleared"):
            validate_scalar_fields(Title, {"name": None})


class TestPlanScalarFieldClaims:
    def test_rejects_empty_fields(self):
        with pytest.raises(StructuredValidationError, match="No changes provided"):
            plan_scalar_field_claims(Title, {})

    def test_reuses_scalar_validation(self):
        specs = plan_scalar_field_claims(Title, {"description": None})
        assert len(specs) == 1
        assert specs[0].field_name == "description"
        assert specs[0].value == ""


class TestValidateScalarFieldsNumericConstraints:
    """Validators defined on model fields are enforced at claim-assertion time."""

    def test_rejects_year_below_minimum(self):
        with pytest.raises(
            StructuredValidationError, match="greater than or equal to 1800"
        ):
            validate_scalar_fields(MachineModel, {"year": 1000})

    def test_rejects_year_above_maximum(self):
        with pytest.raises(
            StructuredValidationError, match="less than or equal to 2100"
        ):
            validate_scalar_fields(MachineModel, {"year": 3000})

    def test_accepts_valid_year(self):
        specs = validate_scalar_fields(MachineModel, {"year": 1997})
        assert len(specs) == 1

    def test_rejects_flipper_count_above_maximum(self):
        with pytest.raises(StructuredValidationError, match="less than or equal to 20"):
            validate_scalar_fields(MachineModel, {"flipper_count": 999})

    def test_accepts_valid_flipper_count(self):
        specs = validate_scalar_fields(MachineModel, {"flipper_count": 12})
        assert len(specs) == 1

    def test_rejects_rating_above_maximum(self):
        with pytest.raises(StructuredValidationError, match="less than or equal to 10"):
            validate_scalar_fields(MachineModel, {"ipdb_rating": 11})

    def test_skips_validators_for_null(self):
        specs = validate_scalar_fields(MachineModel, {"year": None})
        assert len(specs) == 1
        assert specs[0].value == ""

    def test_rejects_person_birth_day_above_maximum(self):
        with pytest.raises(StructuredValidationError, match="less than or equal to 31"):
            validate_scalar_fields(Person, {"birth_day": 32})

    def test_rejects_corporate_entity_year_below_minimum(self):
        with pytest.raises(
            StructuredValidationError, match="greater than or equal to 1800"
        ):
            validate_scalar_fields(CorporateEntity, {"year_start": 100})


class TestGetFieldConstraints:
    """get_field_constraints introspects model validators."""

    def test_machine_model_constraints(self):
        result = get_field_constraints(MachineModel)
        assert result["year"] == FieldConstraintSchema(min=1800, max=2100, step=1)
        assert result["month"] == FieldConstraintSchema(min=1, max=12, step=1)
        assert result["flipper_count"] == FieldConstraintSchema(min=0, max=20, step=1)
        assert result["player_count"] == FieldConstraintSchema(min=1, max=20, step=1)
        assert result["ipdb_rating"] == FieldConstraintSchema(min=0, max=10, step=0.01)
        assert result["ipdb_id"] == FieldConstraintSchema(min=1, step=1)

    def test_person_constraints(self):
        result = get_field_constraints(Person)
        assert result["birth_year"] == FieldConstraintSchema(min=1800, max=2100, step=1)
        assert result["birth_month"] == FieldConstraintSchema(min=1, max=12, step=1)
        assert result["birth_day"] == FieldConstraintSchema(min=1, max=31, step=1)

    def test_corporate_entity_constraints(self):
        result = get_field_constraints(CorporateEntity)
        assert result["year_start"] == FieldConstraintSchema(min=1800, max=2100, step=1)
        assert result["year_end"] == FieldConstraintSchema(min=1800, max=2100, step=1)

    def test_excludes_non_numeric_fields(self):
        result = get_field_constraints(MachineModel)
        assert "name" not in result
        assert "description" not in result


class TestFieldConstraintsEndpoint:
    def test_returns_machine_model_constraints(self, client):
        resp = client.get("/api/field-constraints/model")
        assert resp.status_code == 200
        data = resp.json()
        assert data["year"] == {"min": 1800, "max": 2100, "step": 1}
        assert data["flipper_count"] == {"min": 0, "max": 20, "step": 1}
        # Unbounded max must be omitted, not sent as null — the frontend
        # spreads this object directly into a <NumberField max={...} />.
        assert data["ipdb_id"] == {"min": 1, "step": 1}

    def test_returns_person_constraints(self, client):
        resp = client.get("/api/field-constraints/person")
        assert resp.status_code == 200
        data = resp.json()
        assert "birth_year" in data

    def test_unknown_entity_returns_404(self, client):
        resp = client.get("/api/field-constraints/nonexistent")
        assert resp.status_code == 404


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
