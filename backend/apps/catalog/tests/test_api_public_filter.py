"""Tests for the public filtering API (``GET /api/public/filter/models/``).

The published half of the listing engine: same dimension vocabulary, same
predicate, no roll-up. Coverage: the flat Model grain (including the two
divergences from the listing — unanimous Titles stay Models, Variants need no
flag), the strictness inversions (unknown param names and unknown ``edge``
keys are errors where the listing ignores or matches nothing), and the
route's own rate-limit bucket.
"""

from __future__ import annotations

from typing import Any

from apps.catalog.models import RelationshipType
from apps.catalog.tests.game_builders import _edge, _model, _theme, _title

URL = "/api/public/filter/models/"


def _body(client, query: str = "") -> dict[str, Any]:
    resp = client.get(f"{URL}?{query}" if query else URL)
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["count"] == len(body["public_ids"])
    return body


def _ids(client, query: str = "") -> list[str]:
    ids: list[str] = _body(client, query)["public_ids"]
    return ids


class TestFlatGrain:
    def test_unfiltered_returns_every_live_model(self, client, db):
        t = _title("Solo", "solo")
        _model(t, "solo-m")
        t2 = _title("Duo", "duo")
        _model(t2, "duo-a")
        _model(t2, "duo-b")
        assert _ids(client) == ["duo-a", "duo-b", "solo-m"]

    def test_no_rollup_where_the_listing_rolls_up(self, client, db):
        """The two counts must never be reconciled: a unanimous Title is one
        card on the listing and stays two Models here."""
        t = _title("Uniform", "uniform")
        _model(t, "uniform-a", manufacturer="stern")
        _model(t, "uniform-b", manufacturer="stern")
        assert _ids(client, "manufacturer=stern") == ["uniform-a", "uniform-b"]
        listing = client.get("/api/games/?manufacturer=stern")
        assert listing.json()["count"] == 1

    def test_variant_needs_no_flag_at_flat_grain(self, client, db):
        """The case the old route's ``include_variants`` existed for: at flat
        Model grain a Variant is just a Model."""
        t = _title("Tiered", "tiered")
        parent = _model(t, "tiered-premium", production_status="produced")
        _model(
            t,
            "tiered-le",
            variant_of=parent,
            production_status="announced",
        )
        assert _ids(client, "production_status=announced") == ["tiered-le"]

    def test_deleted_model_and_live_model_under_deleted_title_excluded(
        self, client, db
    ):
        t = _title("Half Gone", "half-gone")
        _model(t, "half-gone-live")
        dead = _model(t, "half-gone-dead")
        dead.status = "deleted"
        dead.save()
        t2 = _title("Orphaned", "orphaned")
        _model(t2, "orphaned-live")
        t2.status = "deleted"
        t2.save()
        assert _ids(client) == ["half-gone-live"]


class TestVocabulary:
    def test_edge_key_and_direction(self, client, db):
        t = _title("Original", "original")
        original = _model(t, "the-original")
        t2 = _title("Knockoff", "knockoff")
        knockoff = _model(t2, "the-knockoff")
        _edge(knockoff, original, RelationshipType.COPY)
        assert _ids(client, "edge=copy") == ["the-knockoff"]
        assert _ids(client, "edge=copy:in") == ["the-original"]

    def test_sparse_preset_pair_widens_to_nulls(self, client, db):
        t = _title("Classified", "classified")
        _model(t, "classified-m", game_format="pinball")
        t2 = _title("Unmarked", "unmarked")
        _model(t2, "unmarked-m")
        t3 = _title("Puck", "puck")
        _model(t3, "puck-m", game_format="shuffle")
        assert _ids(client, "game_format=pinball&game_format=unclassified") == [
            "classified-m",
            "unmarked-m",
        ]
        assert _ids(client, "game_format=pinball") == ["classified-m"]

    def test_repeated_themes_and_on_one_model_without_duplicate_ids(self, client, db):
        _theme("space")
        _theme("horror")
        t = _title("Both", "both")
        _model(t, "both-m", themes=("space", "horror"))
        t2 = _title("One", "one")
        _model(t2, "one-m", themes=("space",))
        # ANDed across repeats; the M2M joins must not duplicate the id.
        assert _ids(client, "theme=space&theme=horror") == ["both-m"]

    def test_unknown_slug_matches_nothing(self, client, db):
        t = _title("Any", "any")
        _model(t, "any-m")
        body = _body(client, "manufacturer=retired-slug")
        assert body == {"count": 0, "public_ids": []}


class TestStrictness:
    def test_unknown_param_name_is_an_error(self, client, db):
        resp = client.get(f"{URL}?edge_type=copy")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["kind"] == "validation_error"
        assert "edge_type" in detail["form_errors"][0]

    def test_q_and_page_are_not_published(self, client, db):
        assert client.get(f"{URL}?q=godzilla").status_code == 422
        assert client.get(f"{URL}?page=2").status_code == 422

    def test_unknown_edge_key_is_an_error_naming_the_vocabulary(self, client, db):
        resp = client.get(f"{URL}?edge=conversionkit")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["kind"] == "validation_error"
        assert "conversionkit" in detail["field_errors"]["edge"]
        assert "conversion_kit" in detail["field_errors"]["edge"]

    def test_known_edge_key_with_direction_is_not_an_error(self, client, db):
        assert client.get(f"{URL}?edge=copy:in").status_code == 200


class TestRateLimit:
    def test_own_bucket_separate_from_the_exports(self, client, db, settings):
        # Squeeze both budgets to 1: exhausting the filter bucket must leave
        # the export bucket serving, and vice versa.
        settings.FILTER_RATELIMIT_IP = (1, 3600)
        settings.EXPORT_RATELIMIT_IP = (1, 3600)
        assert client.get(URL).status_code == 200
        limited = client.get(URL)
        assert limited.status_code == 429
        assert limited["Retry-After"]
        assert limited.json()["detail"]["kind"] == "rate_limit"
        assert client.get("/api/public/export/models/").status_code == 200
