"""Tests for the generic ``/api/entity-autocomplete/`` endpoint.

Covers the wrapper contract (type resolution, unknown-type 400, the result
cap, empty-``q`` top-N), that ``value`` is the identity string the consumer
saves (a slug, not a ``[[…]]`` ref), abbreviation/alias matching, the
``manufacturer · year`` sublabel for ``title`` and ``model``, and the
Postgres-only both-directions diacritic fold.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test import Client

from apps.core.autocomplete import AUTOCOMPLETE_RESULT_LIMIT

ENDPOINT = "/api/entity-autocomplete/"


@pytest.fixture
def api():
    return Client()


@pytest.fixture
def williams(db):
    from apps.catalog.models import Manufacturer

    return Manufacturer.objects.create(name="Williams", slug="williams")


def _make_title_with_model(*, title_name, title_slug, mfr_name, year):
    """Create a title with one non-variant model under a fresh manufacturer,
    so the title's ``manufacturer · year`` sublabel resolves."""
    from apps.catalog.models import (
        CorporateEntity,
        MachineModel,
        Manufacturer,
        Title,
    )

    mfr = Manufacturer.objects.create(name=mfr_name, slug=mfr_name.lower())
    ce = CorporateEntity.objects.create(
        name=mfr_name, slug=f"{mfr_name.lower()}-ce", manufacturer=mfr
    )
    title = Title.objects.create(name=title_name, slug=title_slug)
    model = MachineModel.objects.create(
        title=title,
        name=title_name,
        slug=f"{title_slug}-model",
        corporate_entity=ce,
        year=year,
    )
    return title, model


@pytest.mark.django_db
class TestEntityAutocomplete:
    def test_returns_value_label_sublabel(self, api, williams):
        resp = api.get(ENDPOINT, {"type": "manufacturer", "q": "wil"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results == [{"value": "williams", "label": "Williams", "sublabel": None}]

    def test_value_is_slug_not_wikilink_ref(self, api, williams):
        """``value`` is the bare identity string the consumer saves — the slug,
        not a ``[[manufacturer:williams]]`` wikilink token."""
        resp = api.get(ENDPOINT, {"type": "manufacturer", "q": "wil"})
        value = resp.json()["results"][0]["value"]
        assert value == "williams"
        assert "[[" not in value
        assert ":" not in value

    def test_unknown_type_returns_400(self, api):
        resp = api.get(ENDPOINT, {"type": "nonexistent", "q": ""})
        assert resp.status_code == 400

    def test_cite_is_not_an_autocomplete_type(self, api):
        """``cite`` is picker-only (a custom-flow ``PickerType`` with no
        autocomplete entry), so it 400s here."""
        resp = api.get(ENDPOINT, {"type": "cite", "q": ""})
        assert resp.status_code == 400

    def test_empty_query_returns_top_n(self, api, williams):
        resp = api.get(ENDPOINT, {"type": "manufacturer", "q": ""})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) >= 1

    def test_excludes_deleted_entities(self, api, williams):
        from apps.catalog.models import Manufacturer

        Manufacturer.objects.create(name="Defunct Co", slug="defunct", status="deleted")
        resp = api.get(ENDPOINT, {"type": "manufacturer", "q": ""})
        values = {r["value"] for r in resp.json()["results"]}
        assert "williams" in values
        assert "defunct" not in values

    def test_caps_results_at_limit(self, api, db):
        from apps.catalog.models import Manufacturer

        Manufacturer.objects.bulk_create(
            Manufacturer(name=f"Manufacturer {i:03d}", slug=f"manufacturer-{i:03d}")
            for i in range(AUTOCOMPLETE_RESULT_LIMIT + 10)
        )
        resp = api.get(ENDPOINT, {"type": "manufacturer", "q": "manufacturer"})
        assert len(resp.json()["results"]) == AUTOCOMPLETE_RESULT_LIMIT

    def test_matches_manufacturer_alias(self, api, db):
        from apps.catalog.models import Manufacturer, ManufacturerAlias

        bally = Manufacturer.objects.create(name="Bally", slug="bally")
        ManufacturerAlias.objects.create(manufacturer=bally, value="midway")
        resp = api.get(ENDPOINT, {"type": "manufacturer", "q": "midway"})
        values = {r["value"] for r in resp.json()["results"]}
        assert "bally" in values

    def test_matches_title_abbreviation(self, api, db):
        """``title`` matches on its abbreviations, not just ``name`` — "acdc"
        finds AC/DC."""
        from apps.catalog.models import Title, TitleAbbreviation

        acdc = Title.objects.create(name="AC/DC", slug="acdc")
        TitleAbbreviation.objects.create(title=acdc, value="acdc")
        resp = api.get(ENDPOINT, {"type": "title", "q": "acdc"})
        values = {r["value"] for r in resp.json()["results"]}
        assert "acdc" in values

    def test_title_sublabel_is_manufacturer_year(self, api):
        _make_title_with_model(
            title_name="Medieval Madness",
            title_slug="medieval-madness",
            mfr_name="Williams",
            year=1997,
        )
        resp = api.get(ENDPOINT, {"type": "title", "q": "medieval"})
        result = resp.json()["results"][0]
        assert result["value"] == "medieval-madness"
        assert result["sublabel"] == "Williams · 1997"

    def test_model_sublabel_is_manufacturer_year(self, api):
        _, model = _make_title_with_model(
            title_name="Twilight Zone",
            title_slug="twilight-zone",
            mfr_name="Bally",
            year=1993,
        )
        resp = api.get(ENDPOINT, {"type": "model", "q": "twilight"})
        result = resp.json()["results"][0]
        assert result["value"] == model.slug
        assert result["sublabel"] == "Bally · 1993"

    def test_title_sublabel_none_without_model(self, api, db):
        """A title with no model carries no manufacturer/year, so its sublabel
        is null rather than an empty separator."""
        from apps.catalog.models import Title

        Title.objects.create(name="Orphan Title", slug="orphan-title")
        resp = api.get(ENDPOINT, {"type": "title", "q": "orphan"})
        result = resp.json()["results"][0]
        assert result["sublabel"] is None

    def test_title_sublabel_uses_earliest_non_variant_model(self, api, db):
        """The sublabel reflects the title's *first* model — the earliest
        non-variant active model by ``(year, name)`` — not just any model. A
        later model and an earlier *variant* must both be passed over, so the
        single-row tests above don't actually exercise the selection rule."""
        from apps.catalog.models import (
            CorporateEntity,
            MachineModel,
            Manufacturer,
            Title,
        )

        williams = Manufacturer.objects.create(name="Williams", slug="williams")
        williams_ce = CorporateEntity.objects.create(
            name="Williams", slug="williams-ce", manufacturer=williams
        )
        bally = Manufacturer.objects.create(name="Bally", slug="bally")
        bally_ce = CorporateEntity.objects.create(
            name="Bally", slug="bally-ce", manufacturer=bally
        )

        title = Title.objects.create(name="Theatre of Magic", slug="tom")
        # The first model: earliest non-variant → its Williams/1990 wins.
        MachineModel.objects.create(
            title=title,
            name="ToM",
            slug="tom-1990",
            corporate_entity=williams_ce,
            year=1990,
        )
        # A later non-variant model — passed over (not the earliest).
        later = MachineModel.objects.create(
            title=title,
            name="ToM Remake",
            slug="tom-1995",
            corporate_entity=bally_ce,
            year=1995,
        )
        # An earlier *variant* — earliest by year, but excluded by variant_of.
        MachineModel.objects.create(
            title=title,
            name="ToM LE",
            slug="tom-le",
            corporate_entity=bally_ce,
            year=1985,
            variant_of=later,
        )

        resp = api.get(ENDPOINT, {"type": "title", "q": "theatre"})
        result = resp.json()["results"][0]
        assert result["sublabel"] == "Williams · 1990"

    def test_diacritic_fold_both_directions(self, api, db):
        """On Postgres the engine folds both sides: an accent-free query finds
        an accented title *and* an accented query finds it too. SQLite (dev/CI)
        has no ``unaccent`` — only the exact-diacritic spelling matches."""
        from apps.catalog.models import Title

        Title.objects.create(name="Pokémon", slug="pokemon-fold")
        is_postgres = connection.vendor == "postgresql"

        folded = {
            r["value"]
            for r in api.get(ENDPOINT, {"type": "title", "q": "pokemon"}).json()[
                "results"
            ]
        }
        accented = {
            r["value"]
            for r in api.get(ENDPOINT, {"type": "title", "q": "pokémon"}).json()[
                "results"
            ]
        }

        assert ("pokemon-fold" in accented) is True
        assert ("pokemon-fold" in folded) is is_postgres
