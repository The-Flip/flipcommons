import pytest

from apps.catalog.models import (
    Credit,
    CreditRole,
    Person,
    PersonAlias,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model


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
        # The games embed carries the person's roles per card.
        assert data["games"]["count"] == 1
        card = data["games"]["items"][0]
        assert card["name"] == "Medieval Madness"
        assert card["roles"] == ["Design"]
        assert card["year"] == 1997

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
        names = [c["name"] for c in resp.json()["games"]["items"]]
        assert names == ["New Title", "Old Title", "No Year Title"]


@pytest.mark.django_db
class TestPeopleListAliasFold:
    """The paginated ``GET /`` list and the search section both pair a
    ``Count("credits")`` GROUP-BY sort key with alias matching, so the alias fold must
    stay an ``Exists`` subquery (not a join) — a join would multiply the grouped rows and
    inflate ``credit_count``."""

    def test_q_alias_match_preserves_credit_count(self, client, credit_roles):
        """Match by alias on a person with multiple credits; the count stays exact."""
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
