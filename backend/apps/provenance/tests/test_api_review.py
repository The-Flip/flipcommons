"""Tests for the review queue endpoint."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import CreditRole, Person, Series, Title
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Claim, Source


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="S", slug="s", source_type="editorial", priority=1
    )


def _flag(claim: Claim) -> None:
    claim.needs_review = True
    claim.save(update_fields=["needs_review"])


@pytest.mark.django_db
class TestReviewClaimsDisplay:
    """Wiring check: ``/api/review/claims/`` must populate ``value.display``
    for relationship claims and leave it null for scalars."""

    def test_relationship_claim_value_has_display(self, client, source):
        pm = make_machine_model(name="MM", slug="mm-review", year=1997)
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        role = CreditRole.objects.create(name="Art", slug="art")
        claim = Claim.objects.assert_claim(
            pm,
            "credit",
            {"person": person.pk, "role": role.pk, "exists": True},
            source=source,
            claim_key=f"credit|person:{person.pk}|role:{role.pk}",
        )
        _flag(claim)

        resp = client.get("/api/review/claims/")
        assert resp.status_code == 200
        rows = [r for r in resp.json() if r["field_name"] == "credit"]
        assert len(rows) == 1
        display = rows[0]["value"]["display"]
        assert display is not None
        assert [(p["key"], p["label"]) for p in display["identity"]] == [
            ("person", "Pat Lawlor"),
            ("role", "Art"),
        ]

    def test_title_claim_review_links_internal_only_no_opdb(self, client, source):
        """A flagged ``title`` claim surfaces the internal related-title link
        only; the broken OPDB machine URL was removed."""
        title = Title.objects.create(name="Whirlwind", slug="whirlwind")
        Title.objects.create(name="Whirlwind", slug="whirlwind-opdb", opdb_id="G5pe4")
        pm = make_machine_model(name="Whirlwind", slug="whirlwind-mm")
        claim = Claim.objects.assert_claim(pm, "title", title.public_id, source=source)
        _flag(claim)

        resp = client.get("/api/review/claims/")
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["field_name"] == "title")
        urls = [link["url"] for link in row["review_links"]]
        assert any(url.endswith("/whirlwind-opdb") for url in urls)
        assert not any("opdb.org" in url for url in urls)

    def test_scalar_claim_value_has_null_display(self, client, source):
        series = Series.objects.create(slug="s", name="S")
        claim = Claim.objects.assert_claim(series, "name", "Some Name", source=source)
        _flag(claim)

        resp = client.get("/api/review/claims/")
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["field_name"] == "name")
        assert row["value"]["raw"] == "Some Name"
        assert row["value"]["display"] is None


@pytest.mark.django_db
def test_review_claims_query_count_does_not_scale_with_rows(client, source):
    """The GFK ``Claim.subject`` is accessed inside the per-claim loop;
    without ``prefetch_related("subject")`` each access fires a query."""

    def _seed(start: int, count: int) -> None:
        for i in range(start, start + count):
            series = Series.objects.create(slug=f"s-{i}", name=f"S {i}")
            claim = Claim.objects.assert_claim(
                series, "name", f"Name {i}", source=source
            )
            _flag(claim)

    _seed(start=0, count=2)
    with CaptureQueriesContext(connection) as small_ctx:
        resp = client.get("/api/review/claims/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
    small_count = len(small_ctx.captured_queries)

    _seed(start=2, count=8)
    with CaptureQueriesContext(connection) as big_ctx:
        resp = client.get("/api/review/claims/")
        assert resp.status_code == 200
        assert len(resp.json()) == 10
    big_count = len(big_ctx.captured_queries)

    assert big_count == small_count, (
        f"Query count scaled with row count: {small_count} queries at N=2, "
        f"{big_count} at N=10. Likely a missing prefetch on the GFK "
        f"``Claim.subject``.\n"
        f"Extra queries:\n"
        + "\n".join(q["sql"] for q in big_ctx.captured_queries[small_count:])
    )
