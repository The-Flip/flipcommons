"""ClaimCitationInstance join constraints: CASCADE/PROTECT, unique pair, 0..N/0..N.

``ClaimCitationInstance`` is the support edge for scalar/edit citations — one row
per (claim, instance). These tests lock:

* the happy path (a join row links a claim to a shared instance);
* the unique ``(claim, citation_instance)`` pair (negative);
* the intended 0..N / 0..N cardinality the unique constraint does *not* forbid
  (one claim → many instances, one instance → many claims);
* PROTECT on the instance (shared evidence can't be deleted out from under a
  citing claim) and CASCADE from the claim (the link is wholly owned by it).
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalog.models import Manufacturer
from apps.citation.test_factories import make_citation_source
from apps.provenance.models import CitationInstance, ClaimCitationInstance, Source
from apps.provenance.test_factories import claim_citation_instance, make_claim

pytestmark = pytest.mark.django_db


@pytest.fixture
def source():
    return Source.objects.create(
        name="OPDB", slug="opdb", source_type="database", priority=10
    )


@pytest.fixture
def citation_source():
    return make_citation_source(name="The Encyclopedia of Pinball", source_type="book")


@pytest.fixture
def claim(source):
    mfr = Manufacturer.objects.create(name="Williams", slug="williams")
    return make_claim(mfr, "name", "Williams", ingest_source=source)


@pytest.fixture
def claim2(source):
    mfr = Manufacturer.objects.create(name="Gottlieb", slug="gottlieb")
    return make_claim(mfr, "name", "Gottlieb", ingest_source=source)


def _instance(citation_source, locator=""):
    """A shared evidence row — never sets the legacy ``claim`` FK, so deleting a
    claim exercises the join's CASCADE rather than the old FK's PROTECT path."""
    return CitationInstance.objects.create(
        citation_source=citation_source, locator=locator
    )


class TestCreation:
    def test_links_claim_to_instance(self, claim, citation_source):
        inst = _instance(citation_source, "p. 30")
        link = claim_citation_instance(claim, inst)

        assert link.pk is not None
        assert link.claim == claim
        assert link.citation_instance == inst


class TestUnique:
    def test_duplicate_pair_rejected(self, claim, citation_source):
        inst = _instance(citation_source)
        claim_citation_instance(claim, inst)

        # IntegrityError breaks the connection for the rest of the test; contain
        # it in a savepoint so the post-assert count query still runs.
        with pytest.raises(IntegrityError), transaction.atomic():
            claim_citation_instance(claim, inst)

        assert ClaimCitationInstance.objects.filter(claim=claim).count() == 1


class TestCardinality:
    def test_one_claim_links_many_instances(self, claim, citation_source):
        inst_a = _instance(citation_source, "p. 1")
        inst_b = _instance(citation_source, "p. 2")

        claim_citation_instance(claim, inst_a)
        claim_citation_instance(claim, inst_b)

        linked = {
            link.citation_instance_id
            for link in ClaimCitationInstance.objects.filter(claim=claim)
        }
        assert linked == {inst_a.pk, inst_b.pk}

    def test_one_instance_links_many_claims(self, claim, claim2, citation_source):
        inst = _instance(citation_source)

        claim_citation_instance(claim, inst)
        claim_citation_instance(claim2, inst)

        linked = {
            link.claim_id
            for link in ClaimCitationInstance.objects.filter(citation_instance=inst)
        }
        assert linked == {claim.pk, claim2.pk}


class TestOnDelete:
    def test_protect_blocks_deleting_referenced_instance(self, claim, citation_source):
        inst = _instance(citation_source)
        claim_citation_instance(claim, inst)

        with pytest.raises(ProtectedError):
            inst.delete()

        assert CitationInstance.objects.filter(pk=inst.pk).exists()
        assert ClaimCitationInstance.objects.filter(citation_instance=inst).count() == 1

    def test_cascade_deletes_links_when_claim_deleted(self, claim, citation_source):
        inst = _instance(citation_source)
        claim_citation_instance(claim, inst)

        claim.delete()

        assert not ClaimCitationInstance.objects.filter(citation_instance=inst).exists()
        assert CitationInstance.objects.filter(pk=inst.pk).exists()
