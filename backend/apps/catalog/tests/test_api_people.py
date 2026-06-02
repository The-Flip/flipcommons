import pytest

from apps.catalog.models import (
    Credit,
    CreditRole,
    Person,
    PersonAlias,
    Title,
)
from apps.catalog.tests.conftest import SAMPLE_IMAGES, make_machine_model


class TestPeopleAPI:
    def test_list_people(self, client, person, machine_model, credit_roles):
        role = CreditRole.objects.get(slug="design")
        Credit.objects.create(model=machine_model, person=person, role=role)
        resp = client.get("/api/people/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "Pat Lawlor"
        assert data["items"][0]["credit_count"] == 1

    def test_get_person_detail(self, client, person, machine_model, credit_roles):
        title = Title.objects.create(
            name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4-p"
        )
        machine_model.title = title
        machine_model.save()
        role = CreditRole.objects.get(slug="design")
        Credit.objects.create(model=machine_model, person=person, role=role)
        resp = client.get(f"/api/pages/person/{person.slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Pat Lawlor"
        assert len(data["titles"]) == 1
        assert data["titles"][0]["name"] == "Medieval Madness"
        assert data["titles"][0]["roles"] == ["Design"]
        assert data["titles"][0]["year"] == 1997

    def test_get_person_detail_external_ids(self, client, person):
        person.wikidata_id = "Q98765"
        person.save()
        resp = client.get(f"/api/pages/person/{person.slug}")
        assert resp.status_code == 200
        assert resp.json()["wikidata_id"] == "Q98765"

    def test_get_person_detail_year_desc_nulls_last(
        self, client, person, db, credit_roles
    ):
        role = CreditRole.objects.get(slug="design")
        t1 = Title.objects.create(name="Old Title", slug="old-title", opdb_id="T-old")
        t2 = Title.objects.create(name="New Title", slug="new-title", opdb_id="T-new")
        t3 = Title.objects.create(
            name="No Year Title", slug="no-year-title", opdb_id="T-noyear-p"
        )
        old = make_machine_model(name="Old Game", slug="old-game", year=1990, title=t1)
        new = make_machine_model(name="New Game", slug="new-game", year=2020, title=t2)
        no_year = make_machine_model(name="No Year Game", slug="no-year-game", title=t3)
        for m in (old, new, no_year):
            Credit.objects.create(model=m, person=person, role=role)
        resp = client.get(f"/api/pages/person/{person.slug}")
        names = [t["name"] for t in resp.json()["titles"]]
        assert names == ["New Title", "Old Title", "No Year Title"]


@pytest.mark.django_db
class TestPeopleListParityWithAll:
    """The paginated ``GET /`` must serve the same card data the page rendered via
    ``/all/`` (its source today) — same people, credit_counts, aliases and thumbnails,
    differing only by pagination. Asserted as set-equality + monotonic ``-credit_count``,
    not positional: ``/all/`` carries no ``pk`` tiebreak, so tied counts are unordered
    and a positional diff would be flaky."""

    def _card_keys(self, cards):
        return {
            (c["slug"], c["credit_count"], tuple(c["aliases"]), c["thumbnail_url"])
            for c in cards
        }

    def test_paginated_matches_all_card_data(self, client, credit_roles):
        role = CreditRole.objects.get(slug="design")
        title = Title.objects.create(name="Funhouse", slug="funhouse")
        m_img = make_machine_model(
            name="Funhouse",
            slug="funhouse",
            title=title,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        m_plain = make_machine_model(name="Taxi", slug="taxi", title=title)

        top = Person.objects.create(name="Top", slug="top", status="active")
        mid_a = Person.objects.create(name="Mid A", slug="mid-a", status="active")
        mid_b = Person.objects.create(name="Mid B", slug="mid-b", status="active")
        Person.objects.create(name="Zero", slug="zero", status="active")
        PersonAlias.objects.create(person=mid_a, value="Alias A")

        # top: 2 credits (newest model carries an image → thumbnail);
        # mid_a / mid_b: 1 credit each (a tie); zero: none.
        Credit.objects.create(model=m_img, person=top, role=role)
        Credit.objects.create(model=m_plain, person=top, role=role)
        Credit.objects.create(model=m_img, person=mid_a, role=role)
        Credit.objects.create(model=m_plain, person=mid_b, role=role)

        all_cards = client.get("/api/people/all/").json()
        paginated = client.get("/api/people/").json()
        items = paginated["items"]

        assert paginated["count"] == 4
        # Same card data, regardless of order or pagination.
        assert self._card_keys(items) == self._card_keys(all_cards)
        # Monotonic non-increasing by credit_count (the popularity sort).
        counts = [c["credit_count"] for c in items]
        assert counts == sorted(counts, reverse=True)
        assert items[0]["slug"] == "top"
        # The thumbnail provider actually ran (top + mid_a credited on the imaged model).
        assert any(c["thumbnail_url"] for c in items)

    def test_q_alias_match_preserves_credit_count(self, client, credit_roles):
        """People uniquely combine a ``Count("credits")`` GROUP-BY sort key with alias
        matching. The alias fold must stay an ``Exists`` subquery, not a join — a join
        would multiply the grouped rows and inflate ``credit_count``. Match by alias on a
        person with multiple credits and assert the count is exact."""
        role = CreditRole.objects.get(slug="design")
        title = Title.objects.create(name="Funhouse", slug="funhouse")
        m1 = make_machine_model(name="A", slug="a", title=title)
        m2 = make_machine_model(name="B", slug="b", title=title)
        person = Person.objects.create(name="Obscure", slug="obscure", status="active")
        PersonAlias.objects.create(person=person, value="Famous")
        Credit.objects.create(model=m1, person=person, role=role)
        Credit.objects.create(model=m2, person=person, role=role)

        body = client.get("/api/people/", {"q": "famous"}).json()
        assert body["count"] == 1
        assert [c["slug"] for c in body["items"]] == ["obscure"]
        assert body["items"][0]["credit_count"] == 2
