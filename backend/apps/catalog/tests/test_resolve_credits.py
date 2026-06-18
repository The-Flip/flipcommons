"""Tests for credit claim resolution (resolve_credits)."""

import pytest

from apps.catalog.models import Credit, CreditRole, Person
from apps.catalog.resolve import resolve_all_credits
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import Claim, Source


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


def _assert_credit_claim(machine, person_pk, role_slug, source):
    """Helper to create a credit claim via the manager."""
    role = CreditRole.objects.get(slug=role_slug)
    claim_key, value = build_relationship_claim(
        "credit", {"person": person_pk, "role": role.pk}
    )
    Claim.objects.assert_claim(
        machine, "credit", value, source=source, claim_key=claim_key
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
