"""Tests for provenance helpers: active_claims(), citation_instances(), build_sources()."""

import pytest

from apps.catalog.models import CreditRole, Person, Series
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.helpers import (
    active_claims,
    citation_instances,
    claims_prefetch,
)
from apps.provenance.models import Claim
from apps.provenance.schemas import ClaimDisplayValueSchema
from apps.provenance.sources import build_sources
from apps.provenance.test_factories import make_claim, make_ingest_source


@pytest.fixture
def source():
    return make_ingest_source(
        name="Test", slug="test", source_type="database", priority=100
    )


@pytest.mark.django_db
class TestActiveClaims:
    def test_returns_list_when_prefetched(self, source):
        series = Series.objects.create(slug="s", name="S")
        make_claim(series, "name", "S", ingest_source=source)

        loaded = Series.objects.prefetch_related(claims_prefetch()).get(pk=series.pk)

        claims = active_claims(loaded)
        assert isinstance(claims, list)
        assert {c.field_name for c in claims} == {"name"}

    def test_raises_when_not_prefetched(self):
        series = Series.objects.create(slug="s", name="S")

        with pytest.raises(AssertionError, match="claims_prefetch"):
            active_claims(series)


@pytest.mark.django_db
class TestCitationInstances:
    def test_returns_list_when_prefetched(self, source):
        series = Series.objects.create(slug="s", name="S")
        make_claim(series, "name", "S", ingest_source=source)

        loaded = Series.objects.prefetch_related(claims_prefetch()).get(pk=series.pk)
        claim = active_claims(loaded)[0]

        instances = citation_instances(claim)
        assert isinstance(instances, list)

    def test_raises_when_claim_not_prefetched(self, source):
        series = Series.objects.create(slug="s", name="S")
        make_claim(series, "name", "S", ingest_source=source)
        bare_claim = Claim.objects.get(object_id=series.pk, field_name="name")

        with pytest.raises(AssertionError, match="claims_prefetch"):
            citation_instances(bare_claim)


@pytest.mark.django_db
class TestBuildSources:
    """Wiring check: ``build_sources()`` must populate ``value.display`` for
    relationship claims and leave it null for scalars. Guards against the
    helper being called with an empty ``LabelLookup``."""

    def test_relationship_claim_value_has_display(self, source):
        pm = make_machine_model(name="MM", slug="mm", production_year=1997)
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        role = CreditRole.objects.create(name="Art", slug="art")
        make_claim(
            pm,
            "credit",
            {"person": person.pk, "role": role.pk, "exists": True},
            ingest_source=source,
            claim_key=f"credit|person:{person.pk}|role:{role.pk}",
        )

        loaded = pm.__class__.objects.prefetch_related(claims_prefetch()).get(pk=pm.pk)
        sources = build_sources(type(loaded), active_claims(loaded))
        credit = next(s for s in sources if s.field_name == "credit")

        assert isinstance(credit.value.display, ClaimDisplayValueSchema)
        assert [(p.key, p.label) for p in credit.value.display.identity] == [
            ("person", "Pat Lawlor"),
            ("role", "Art"),
        ]

    def test_scalar_claim_value_has_null_display(self, source):
        series = Series.objects.create(slug="s", name="S")
        make_claim(series, "name", "S", ingest_source=source)

        loaded = Series.objects.prefetch_related(claims_prefetch()).get(pk=series.pk)
        sources = build_sources(type(loaded), active_claims(loaded))

        assert sources[0].value.raw == "S"
        assert sources[0].value.display is None
