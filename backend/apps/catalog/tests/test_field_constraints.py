"""Tests for the model-driven field-constraint introspection (engine read-side).

Covers ``get_field_constraints`` and the ``GET /field-constraints/{entity_type}``
endpoint it backs — numeric min/max/step metadata derived from each model's
declared validators.
"""

from __future__ import annotations

from apps.catalog.engine.entity_api.field_constraints import (
    FieldConstraintSchema,
    get_field_constraints,
)
from apps.catalog.models import CorporateEntity, MachineModel, Person


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
