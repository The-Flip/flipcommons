"""Tests for the per-entity Sources page endpoint, plus the scalar
citation-join write path its citation payload depends on."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.test_factories import make_user
from apps.catalog.models import Title
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.test_factories import make_citation_link, make_citation_source
from apps.claim_edit.claim_write import ClaimSpec, execute_claims
from apps.provenance.models import ClaimCitationInstance
from apps.provenance.schemas import CitationInstanceCreateSchema
from apps.provenance.test_factories import (
    cite_claim,
    make_citation_instance,
    make_claim,
    user_changeset,
)

User = get_user_model()


@pytest.fixture
def title(db, bootstrap_source):
    title = Title.objects.create(name="Medieval Madness", slug="medieval-madness")
    make_claim(title, "name", "Medieval Madness", ingest_source=bootstrap_source)
    return title


@pytest.fixture
def citation_source(db):
    source = make_citation_source(name="Williams Flyer", source_type="web")
    make_citation_link(
        citation_source=source,
        link_type="homepage",
        url="https://example.com/flyer",
        label="Scan",
    )
    return source


def _citations(body, field_name: str):
    """Every citation carried by any claim of *field_name*."""
    return [
        citation
        for claim in body["sources"]
        if claim["field_name"] == field_name
        for citation in claim["citations"]
    ]


@pytest.mark.django_db
class TestSourcesPageCitations:
    def test_claim_carries_its_attached_citation_with_link_details(
        self, client, user, title, citation_source
    ):
        changeset = user_changeset(user, note="Documented the flyer")
        name_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=changeset
        )
        cite_claim(name_claim, citation_source=citation_source, locator="p. 2")

        resp = client.get("/api/pages/sources/title/medieval-madness/")

        assert resp.status_code == 200
        citations = _citations(resp.json(), "name")
        assert len(citations) == 1
        assert citations[0]["source_name"] == "Williams Flyer"
        assert citations[0]["locator"] == "p. 2"
        assert citations[0]["links"] == [
            {
                "url": "https://example.com/flyer",
                "link_type": "homepage",
                "display_name": "Scan",
            }
        ]
        # A root source has no parent to name.
        assert citations[0]["root_name"] is None

    def test_cited_child_carries_its_parent_work(self, client, user, title):
        """A periodical issue is ambiguous without the periodical it belongs to,
        so the Sources page carries the parent alongside the child."""
        periodical = make_citation_source(name="Billboard", source_type="periodical")
        issue = make_citation_source(
            name="July 27, 1940", source_type="periodical", parent=periodical
        )
        changeset = user_changeset(user, note="Dated from the trade ad")
        name_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=changeset
        )
        cite_claim(name_claim, citation_source=issue, locator="p. 42")

        resp = client.get("/api/pages/sources/title/medieval-madness/")

        assert resp.status_code == 200
        citations = _citations(resp.json(), "name")
        assert len(citations) == 1
        assert citations[0]["source_name"] == "July 27, 1940"
        assert citations[0]["root_name"] == "Billboard"

    def test_shared_evidence_rides_every_claim_it_backs(
        self, client, user, title, citation_source
    ):
        """One instance fanned across a save appears on each claim it supports.

        The page consolidates them per value client-side; the wire format
        carries the full support edge for every claim.
        """
        changeset = user_changeset(user, note="Grouped edit")
        name_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=changeset
        )
        desc_claim = make_claim(
            title, "description", "Updated copy", user=user, changeset=changeset
        )
        cite_claim(name_claim, citation_source=citation_source, locator="p. 3")
        cite_claim(desc_claim, citation_source=citation_source, locator="p. 3")

        body = client.get("/api/pages/sources/title/medieval-madness/").json()

        for field_name in ("name", "description"):
            assert [c["locator"] for c in _citations(body, field_name)] == ["p. 3"]

    def test_uncited_claim_carries_an_empty_citation_list(self, client, user, title):
        make_claim(
            title,
            "description",
            "Cleanup",
            user=user,
            changeset=user_changeset(user, note="Uncited cleanup"),
        )

        body = client.get("/api/pages/sources/title/medieval-madness/").json()

        assert _citations(body, "description") == []

    def test_claims_expose_the_claim_key_that_scopes_resolution(self, client, title):
        """The page groups by claim_key, so it must cross the wire."""
        body = client.get("/api/pages/sources/title/medieval-madness/").json()

        keys = {c["claim_key"] for c in body["sources"] if c["field_name"] == "name"}
        assert keys == {"name"}

    def test_soft_deleted_entity_still_returns_sources(
        self, client, user, title, citation_source
    ):
        """Soft-delete is soft: sources page remains inspectable by public_id.

        Policy: provenance surfaces intentionally use the default manager
        (not ``.active()``) so deleted entities keep their claims and
        citations visible to direct API callers. See ``sources_page``
        docstring.
        """
        changeset = user_changeset(user, note="Documented the flyer")
        cited_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=changeset
        )
        cite_claim(cited_claim, citation_source=citation_source)

        title.status = "deleted"
        title.save(update_fields=["status"])

        resp = client.get("/api/pages/sources/title/medieval-madness/")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["sources"]) >= 1
        assert len(_citations(body, "name")) == 1


@pytest.mark.django_db
class TestScalarCitationJoin:
    def test_execute_claims_fans_a_join_row_to_every_claim(
        self, user, title, citation_source
    ):
        # The engine's scalar-cite path mints ONE shared instance per distinct
        # content spec and fans a ClaimCitationInstance support edge to every
        # claim in the save — no per-claim clones.
        execute_claims(
            title,
            [
                ClaimSpec(field_name="name", value="Medieval Madness (1997)"),
                ClaimSpec(field_name="description", value="Updated copy"),
            ],
            user=user,
            citations=[
                CitationInstanceCreateSchema(
                    citation_source_id=citation_source.pk, locator="p. 9"
                )
            ],
        )

        links = ClaimCitationInstance.objects.select_related(
            "citation_instance", "claim"
        )
        assert links.count() == 2
        instances = {link.citation_instance for link in links}
        assert len(instances) == 1  # shared evidence, not a clone per claim
        instance = instances.pop()
        assert instance.citation_source_id == citation_source.pk
        assert instance.locator == "p. 9"
        assert {link.claim.field_name for link in links} == {"name", "description"}

    def test_execute_claims_dedupes_identical_citation_specs(
        self, user, title, citation_source
    ):
        # The same (source, locator) entered twice is one piece of evidence:
        # one instance, one join row per claim.
        spec = CitationInstanceCreateSchema(
            citation_source_id=citation_source.pk, locator="p. 9"
        )
        execute_claims(
            title,
            [ClaimSpec(field_name="name", value="Medieval Madness (1997)")],
            user=user,
            citations=[spec, spec.model_copy()],
        )
        assert ClaimCitationInstance.objects.count() == 1

    def test_execute_claims_attaches_multiple_citations(
        self, user, title, citation_source
    ):
        # Distinct specs each mint their own shared instance — a save can
        # carry several pieces of evidence.
        execute_claims(
            title,
            [ClaimSpec(field_name="name", value="Medieval Madness (1997)")],
            user=user,
            citations=[
                CitationInstanceCreateSchema(
                    citation_source_id=citation_source.pk, locator="p. 9"
                ),
                CitationInstanceCreateSchema(
                    citation_source_id=citation_source.pk, locator="p. 12"
                ),
            ],
        )
        links = ClaimCitationInstance.objects.select_related("citation_instance")
        assert len({link.claim_id for link in links}) == 1
        assert {link.citation_instance.locator for link in links} == {"p. 9", "p. 12"}

    def test_execute_claims_persists_the_quote(self, user, title, citation_source):
        execute_claims(
            title,
            [ClaimSpec(field_name="name", value="Medieval Madness (1997)")],
            user=user,
            citations=[
                CitationInstanceCreateSchema(
                    citation_source_id=citation_source.pk,
                    locator="p. 9",
                    quote="Released in 1997.",
                )
            ],
        )
        link = ClaimCitationInstance.objects.select_related("citation_instance").get()
        assert link.citation_instance.quote == "Released in 1997."

    def test_execute_claims_splits_specs_differing_only_by_quote(
        self, user, title, citation_source
    ):
        # A differing quote is a distinct piece of evidence: same source and
        # locator, two quotes → two instances, not one collapsed row.
        execute_claims(
            title,
            [ClaimSpec(field_name="name", value="Medieval Madness (1997)")],
            user=user,
            citations=[
                CitationInstanceCreateSchema(
                    citation_source_id=citation_source.pk,
                    locator="p. 9",
                    quote="Released in 1997.",
                ),
                CitationInstanceCreateSchema(
                    citation_source_id=citation_source.pk,
                    locator="p. 9",
                    quote="Designed by Brian Eddy.",
                ),
            ],
        )
        links = ClaimCitationInstance.objects.select_related("citation_instance")
        assert {link.citation_instance.quote for link in links} == {
            "Released in 1997.",
            "Designed by Brian Eddy.",
        }


def _q(fn: Callable[[], object]) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


def _seed_cited_claims(pm, citation_source, start: int, n: int) -> None:
    """Add ``n`` claims to ``pm``, each by its own actor and each carrying both
    an attached citation instance and an inline ``[[cite:id:N]]`` marker.

    Scales every axis the sources payload builds per claim, so a batch that
    regresses to a per-claim query shows up as a query-count growth:
    ``resolve_display_context`` and ``resolve_inline_citations`` each issue one
    query for the whole claim list, and both ``citation_instances_prefetch``
    and ``resolve_inline_citations`` prefetch ``citation_source__links``, which
    ``citation_schema`` reads for every citation it serializes. Dropping the
    ``to_attr`` prefetch fails loudly (``citation_instances()`` raises), but
    dropping either ``links`` prefetch would N+1 silently — hence both a join
    row and a marker on every claim.
    """
    for i in range(start, start + n):
        instance = make_citation_instance(citation_source=citation_source)
        # Namespaced names park in extra_data, so each claim is its own field
        # without needing 20 real columns.
        claim = make_claim(
            pm,
            f"probe.note_{i}",
            f"Copy [[cite:id:{instance.pk}]] {i}",
            user=make_user(),
        )
        cite_claim(claim, citation_source=citation_source, locator=f"p. {i}")


@pytest.mark.django_db
def test_sources_page_does_not_scale_queries_with_claim_count(client, bootstrap_source):
    """GET /api/pages/sources/... query count must not grow with N claims.

    Distinct actors and distinct fields per claim, so a regression in the
    display-context batch, the inline-citation batch or either citation-links
    prefetch shows up here.
    """
    pm = make_machine_model(name="MM3", slug="mm-z")
    citation_source = make_citation_source(name="Flyer", source_type="web")

    _seed_cited_claims(pm, citation_source, 0, 2)
    base = _q(lambda: client.get("/api/pages/sources/model/mm-z/"))

    _seed_cited_claims(pm, citation_source, 2, 18)
    scaled = _q(lambda: client.get("/api/pages/sources/model/mm-z/"))

    # Guard against a vacuous pass: the endpoint must actually be serving the
    # claims we seeded, not 404ing or returning an empty list.
    resp = client.get("/api/pages/sources/model/mm-z/")
    assert resp.status_code == 200
    body = resp.json()["sources"]
    probes = [c for c in body if c["field_name"].startswith("probe.")]
    assert len(probes) == 20
    # One attached instance plus one inline marker on each.
    assert sum(len(claim["citations"]) for claim in probes) == 40

    assert scaled == base, (
        f"sources page scales queries with claim count: {base} -> {scaled}."
    )


@pytest.mark.django_db
class TestSourcesPageParkedFields:
    """Parked source fields are hidden from the Sources page."""

    def test_parked_field_is_hidden(self, client, bootstrap_source):
        pm = make_machine_model(name="MM4", slug="mm-parked")
        make_claim(pm, "year", 1997, ingest_source=bootstrap_source)
        make_claim(
            pm,
            "opdb.images",
            [{"urls": {"large": "https://example.com/a.jpg"}}],
            ingest_source=bootstrap_source,
        )

        resp = client.get("/api/pages/sources/model/mm-parked/")
        assert resp.status_code == 200
        fields = {c["field_name"] for c in resp.json()["sources"]}
        assert "opdb.images" not in fields
        assert "year" in fields

    def test_unlisted_parked_field_still_shows(self, client, bootstrap_source):
        """Hiding is by name, not by the dot the ingest namespaces happen to use.

        A field nobody has listed is a data surprise worth seeing — the debug
        panel makes the same call for the same reason.
        """
        pm = make_machine_model(name="MM5", slug="mm-surprise")
        make_claim(pm, "wat.mystery", "?", ingest_source=bootstrap_source)

        resp = client.get("/api/pages/sources/model/mm-surprise/")
        assert resp.status_code == 200
        fields = {c["field_name"] for c in resp.json()["sources"]}
        assert "wat.mystery" in fields
