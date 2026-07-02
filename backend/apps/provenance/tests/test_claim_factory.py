"""Tests for Claim.for_object() factory classmethod."""

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.catalog.models import Series, Title
from apps.provenance.models import Claim


@pytest.mark.django_db
class TestClaimForObject:
    def test_sets_content_type_from_object(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        claim = Claim.for_object(series, field_name="name", value="Test")
        assert claim.content_type_id == ContentType.objects.get_for_model(Series).pk

    def test_sets_object_id_from_object(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        claim = Claim.for_object(series, field_name="name", value="Test")
        assert claim.object_id == series.pk

    def test_sets_field_name_and_value(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        claim = Claim.for_object(series, field_name="name", value="Eight Ball")
        assert claim.field_name == "name"
        assert claim.value == "Eight Ball"

    def test_claim_key_defaults_to_empty(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        claim = Claim.for_object(series, field_name="name", value="Test")
        assert claim.claim_key == ""

    def test_claim_key_can_be_set(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        claim = Claim.for_object(
            series, field_name="name", value="Test", claim_key="name"
        )
        assert claim.claim_key == "name"

    def test_kwargs_passed_through(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        claim = Claim.for_object(
            series,
            field_name="name",
            value="Test",
            is_active=False,
        )
        assert claim.is_active is False

    def test_different_model_types_get_different_content_types(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        title = Title.objects.create(slug="test-title", name="Test Title")
        series_claim = Claim.for_object(series, field_name="name", value="A")
        title_claim = Claim.for_object(title, field_name="name", value="B")
        assert series_claim.content_type_id != title_claim.content_type_id

    def test_returns_unsaved_instance(self):
        series = Series.objects.create(slug="test-series", name="Test Series")
        claim = Claim.for_object(series, field_name="name", value="Test")
        assert claim.pk is None
