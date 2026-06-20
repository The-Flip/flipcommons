"""Tests for credit claim resolution (resolve_credits)."""

import pytest

from apps.catalog.models import Credit, CreditRole, MachineModel, Person, Series
from apps.catalog.resolve import resolve_all_credits, resolve_all_series_credits
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import Claim, Source
from apps.provenance.resolution import resolve_after_mutation, resolve_entities_bulk


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=10
    )


@pytest.fixture
def high_source(db):
    return Source.objects.create(
        name="Editorial", slug="editorial", source_type="editorial", priority=100
    )


@pytest.fixture
def person(db):
    return Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")


@pytest.fixture
def person2(db):
    return Person.objects.create(name="John Youssi", slug="john-youssi")


@pytest.fixture
def machine(db):
    return make_machine_model(name="Medieval Madness", slug="medieval-madness")


@pytest.fixture
def series(db):
    return Series.objects.create(name="World Cup Soccer", slug="world-cup-soccer")


def _assert_credit_claim(subject, person_pk, role_slug, source, *, exists=True):
    """Helper to create a credit claim on any valid subject via the manager."""
    role = CreditRole.objects.get(slug=role_slug)
    claim_key, value = build_relationship_claim(
        "credit", {"person": person_pk, "role": role.pk}, exists=exists
    )
    Claim.objects.assert_claim(
        subject, "credit", value, source=source, claim_key=claim_key
    )


class TestResolveCredits:
    def test_basic_materialization(self, machine, person, source, credit_roles):
        _assert_credit_claim(machine, person.pk, "design", source)
        resolve_all_credits(subject_ids={machine.pk})

        assert Credit.objects.filter(
            model=machine, person=person, role__slug="design"
        ).exists()

    def test_multiple_credits(self, machine, person, person2, source, credit_roles):
        _assert_credit_claim(machine, person.pk, "design", source)
        _assert_credit_claim(machine, person2.pk, "art", source)
        resolve_all_credits(subject_ids={machine.pk})

        assert Credit.objects.filter(model=machine).count() == 2
        assert Credit.objects.filter(
            model=machine, person=person, role__slug="design"
        ).exists()
        assert Credit.objects.filter(
            model=machine, person=person2, role__slug="art"
        ).exists()

    def test_idempotent(self, machine, person, source, credit_roles):
        _assert_credit_claim(machine, person.pk, "design", source)
        resolve_all_credits(subject_ids={machine.pk})
        resolve_all_credits(subject_ids={machine.pk})

        assert Credit.objects.filter(model=machine).count() == 1

    def test_removes_stale_credits(
        self, machine, person, person2, source, credit_roles
    ):
        """If a credit claim is deactivated, resolution removes the Credit."""
        _assert_credit_claim(machine, person.pk, "design", source)
        _assert_credit_claim(machine, person2.pk, "art", source)
        resolve_all_credits(subject_ids={machine.pk})
        assert Credit.objects.filter(model=machine).count() == 2

        # Deactivate the art credit claim.
        Claim.objects.filter(
            field_name="credit", claim_key__contains=str(person2.pk)
        ).update(is_active=False)
        resolve_all_credits(subject_ids={machine.pk})

        assert Credit.objects.filter(model=machine).count() == 1
        assert not Credit.objects.filter(model=machine, person=person2).exists()

    def test_exists_false_dispute(
        self, machine, person, source, high_source, credit_roles
    ):
        """A higher-priority exists=False claim prevents materialization."""
        _assert_credit_claim(machine, person.pk, "design", source)
        resolve_all_credits(subject_ids={machine.pk})
        assert Credit.objects.filter(model=machine).count() == 1

        # Higher-priority source disputes the credit.
        design_role = CreditRole.objects.get(slug="design")
        claim_key, value = build_relationship_claim(
            "credit", {"person": person.pk, "role": design_role.pk}, exists=False
        )
        Claim.objects.assert_claim(
            machine, "credit", value, source=high_source, claim_key=claim_key
        )
        resolve_all_credits(subject_ids={machine.pk})

        assert Credit.objects.filter(model=machine).count() == 0

    def test_multi_source_union(
        self, machine, person, person2, source, high_source, credit_roles
    ):
        """Credits from multiple sources are unioned (each claim_key is independent)."""
        _assert_credit_claim(machine, person.pk, "design", source)
        art_role = CreditRole.objects.get(slug="art")
        claim_key, value = build_relationship_claim(
            "credit", {"person": person2.pk, "role": art_role.pk}
        )
        Claim.objects.assert_claim(
            machine, "credit", value, source=high_source, claim_key=claim_key
        )
        resolve_all_credits(subject_ids={machine.pk})

        assert Credit.objects.filter(model=machine).count() == 2

    def test_unresolved_pk_warning(self, machine, source, caplog, credit_roles):
        """Credit claim for a non-existent person PK logs a warning."""
        design_role = CreditRole.objects.get(slug="design")
        claim_key, value = build_relationship_claim(
            "credit", {"person": 99999, "role": design_role.pk}
        )
        Claim.objects.assert_claim(
            machine, "credit", value, source=source, claim_key=claim_key
        )
        resolve_all_credits(subject_ids={machine.pk})

        assert Credit.objects.filter(model=machine).count() == 0
        assert "Unresolved person" in caplog.text


class TestResolveSeriesCredits:
    """Series credits resolve through the subject-parameterized core."""

    def test_basic_materialization(self, series, person, source, credit_roles):
        _assert_credit_claim(series, person.pk, "design", source)
        resolve_all_series_credits(subject_ids={series.pk})

        assert Credit.objects.filter(
            series=series, person=person, role__slug="design"
        ).exists()

    def test_idempotent(self, series, person, source, credit_roles):
        _assert_credit_claim(series, person.pk, "design", source)
        resolve_all_series_credits(subject_ids={series.pk})
        resolve_all_series_credits(subject_ids={series.pk})

        assert Credit.objects.filter(series=series).count() == 1

    def test_removes_stale_credits(self, series, person, source, credit_roles):
        """Superseding a credit with exists=False deletes the Credit row."""
        _assert_credit_claim(series, person.pk, "design", source)
        resolve_all_series_credits(subject_ids={series.pk})
        assert Credit.objects.filter(series=series).count() == 1

        _assert_credit_claim(series, person.pk, "design", source, exists=False)
        resolve_all_series_credits(subject_ids={series.pk})
        assert Credit.objects.filter(series=series).count() == 0

    def test_exists_false_dispute(
        self, series, person, source, high_source, credit_roles
    ):
        """A higher-priority exists=False claim prevents materialization."""
        _assert_credit_claim(series, person.pk, "design", source)
        resolve_all_series_credits(subject_ids={series.pk})
        assert Credit.objects.filter(series=series).count() == 1

        _assert_credit_claim(series, person.pk, "design", high_source, exists=False)
        resolve_all_series_credits(subject_ids={series.pk})
        assert Credit.objects.filter(series=series).count() == 0

    def test_isolated_from_model_credits(
        self, series, machine, person, source, credit_roles
    ):
        """The model/series XOR means each pass only touches its own rows."""
        _assert_credit_claim(machine, person.pk, "design", source)
        _assert_credit_claim(series, person.pk, "design", source)
        resolve_all_credits(subject_ids={machine.pk})
        resolve_all_series_credits(subject_ids={series.pk})

        assert Credit.objects.filter(model=machine, series__isnull=True).count() == 1
        assert Credit.objects.filter(series=series, model__isnull=True).count() == 1


class TestSeriesCreditDispatch:
    """Series credits resolve through the public dispatch seam (proves the
    ``_get_custom_dispatch`` binding, not just the resolver in isolation —
    the binding is a stringly-typed ``getattr`` invisible to mypy)."""

    def test_per_entity_dispatch(self, series, person, source, credit_roles):
        _assert_credit_claim(series, person.pk, "design", source)
        resolve_after_mutation(series, ["credit"])

        assert Credit.objects.filter(series=series, person=person).exists()

    def test_bulk_dispatch(self, series, person, source, credit_roles):
        _assert_credit_claim(series, person.pk, "design", source)
        resolve_entities_bulk(Series, {series.pk}, {"credit"})

        assert Credit.objects.filter(series=series, person=person).exists()

    def test_model_credit_dispatch_unaffected(
        self, machine, person, source, credit_roles
    ):
        """Adding ``credit`` to the custom dispatch must not hijack the
        MachineModel bulk path (it routes via ``_mm_relationship_resolvers``)."""
        _assert_credit_claim(machine, person.pk, "design", source)
        resolve_entities_bulk(MachineModel, {machine.pk}, {"credit"})

        assert Credit.objects.filter(model=machine, person=person).exists()
