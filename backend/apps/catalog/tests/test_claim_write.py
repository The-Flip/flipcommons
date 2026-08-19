"""Tests for the generic interactive claim-write engine (claim_write)."""

from __future__ import annotations

import pytest

from apps.catalog.models import CorporateEntity, MachineModel, Person, Title
from apps.claim_edit.claim_write import (
    plan_scalar_field_claims,
    validate_scalar_fields,
)
from apps.core.exceptions import StructuredValidationError


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
            validate_scalar_fields(MachineModel, {"production_year": 1000})

    def test_rejects_year_above_maximum(self):
        with pytest.raises(
            StructuredValidationError, match="less than or equal to 2100"
        ):
            validate_scalar_fields(MachineModel, {"production_year": 3000})

    def test_accepts_valid_year(self):
        specs = validate_scalar_fields(MachineModel, {"production_year": 1997})
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
        specs = validate_scalar_fields(MachineModel, {"production_year": None})
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
