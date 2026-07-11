"""Tests for the global search page endpoint ``GET /api/pages/search``.

The endpoint stacks three entity sections (Titles → Manufacturers → People), each
reusing its listing-page ``q`` + card serializer, capped at 10 with a ``has_more``
flag. These tests pin: the ``<3``-char no-work guard, per-section matching + card
shape, the 10-cap, the diacritic dev/prod split, fixed section order, that a section
preserves its listing sort, the all-empty case, and a constant-query N+1 guard.

Global search also has a **description tier**: rows matched only by their
``DescribedModel.description`` rank *below* the name/alias tier, and — unlike the name
tier — never feed the record-creation ``query_count`` gate. Those tests pin the tier
surfacing per section, the name-before-description ranking, combined ``has_more``, and
the gate staying blind to description-only matches.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Credit, CreditRole, Manufacturer, Person, Title
from apps.catalog.tests.conftest import SAMPLE_IMAGES, make_machine_model
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim

CARD_KEYS = {
    "titles": {"name", "slug", "year", "model_count", "manufacturer", "thumbnail_url"},
    "manufacturers": {"name", "slug", "model_count", "thumbnail_url"},
    "people": {"name", "slug", "aliases", "credit_count", "thumbnail_url"},
}


def _make_manufacturer(
    name: str, slug: str, source: Source, description: str = ""
) -> Manufacturer:
    mfr = Manufacturer.objects.create(name=name, slug=slug, description=description)
    make_claim(mfr, "name", name, ingest_source=source)
    return mfr


def _make_person(name: str, slug: str, source: Source, description: str = "") -> Person:
    p = Person.objects.create(name=name, slug=slug, description=description)
    make_claim(p, "name", name, ingest_source=source)
    return p


@pytest.fixture
def nova_in_each_section(bootstrap_source):
    """One matching row per section for the term ``nova``."""
    Title.objects.create(name="Nova Madness", slug="nova-madness")
    _make_manufacturer("Nova Games", "nova-games", bootstrap_source)
    _make_person("Nova Lawlor", "nova-lawlor", bootstrap_source)


def test_short_q_returns_empty_sections_and_does_no_db_work(
    client, db, django_assert_num_queries
):
    """Trimmed ``q`` shorter than 3 chars → all sections empty, no queries run."""
    with django_assert_num_queries(0):
        resp = client.get("/api/pages/search?q=no")
    assert resp.status_code == 200
    data = resp.json()
    for section in ("titles", "manufacturers", "people"):
        assert data[section] == {"items": [], "has_more": False}


def test_whitespace_q_is_trimmed_below_threshold(client, db):
    """A two-char term padded with spaces is still below the 3-char floor."""
    resp = client.get("/api/pages/search?q=%20%20ab%20%20")
    data = resp.json()
    assert all(not data[s]["items"] for s in ("titles", "manufacturers", "people"))


def test_basic_q_matches_each_section_with_card_shape(client, nova_in_each_section):
    resp = client.get("/api/pages/search?q=nova")
    assert resp.status_code == 200
    data = resp.json()
    assert data["titles"]["items"][0]["name"] == "Nova Madness"
    assert data["manufacturers"]["items"][0]["name"] == "Nova Games"
    assert data["people"]["items"][0]["name"] == "Nova Lawlor"
    for section, keys in CARD_KEYS.items():
        assert set(data[section]["items"][0]) == keys
        assert data[section]["has_more"] is False


def test_section_caps_at_ten_and_sets_has_more(client, db, bootstrap_source):
    """11 matches → 10 cards + ``has_more``; the other sections stay empty."""
    for i in range(11):
        _make_manufacturer(f"Capco {i:02d}", f"capco-{i:02d}", bootstrap_source)
    data = client.get("/api/pages/search?q=capco").json()
    assert len(data["manufacturers"]["items"]) == 10
    assert data["manufacturers"]["has_more"] is True
    assert data["titles"] == {"items": [], "has_more": False}
    assert data["people"] == {"items": [], "has_more": False}


def test_exactly_ten_matches_does_not_set_has_more(client, db, bootstrap_source):
    for i in range(10):
        _make_manufacturer(f"Tenco {i:02d}", f"tenco-{i:02d}", bootstrap_source)
    data = client.get("/api/pages/search?q=tenco").json()
    assert len(data["manufacturers"]["items"]) == 10
    assert data["manufacturers"]["has_more"] is False


def test_q_diacritic_is_backend_specific(client, db):
    """Folds diacritics on Postgres only (prod), plain ``icontains`` on SQLite (dev/CI)
    — the same documented gap the listing endpoints carry. Exact spelling matches on
    both backends."""
    Title.objects.create(name="Pokémon Pinball", slug="pokemon-pinball-search")
    folded = client.get("/api/pages/search?q=pokemon").json()["titles"]
    exact = client.get("/api/pages/search?q=Pok%C3%A9mon").json()["titles"]
    assert len(exact["items"]) == 1
    expected = 1 if connection.vendor == "postgresql" else 0
    assert len(folded["items"]) == expected


def test_section_order_is_titles_manufacturers_people(client, nova_in_each_section):
    """The wire payload renders sections in fixed declaration order."""
    data = client.get("/api/pages/search?q=nova").json()
    assert list(data.keys()) == ["titles", "manufacturers", "people"]


def test_no_match_returns_all_empty_sections(client, nova_in_each_section):
    data = client.get("/api/pages/search?q=zzzznomatch").json()
    for section in ("titles", "manufacturers", "people"):
        assert data[section] == {"items": [], "has_more": False}


def test_people_section_preserves_listing_order(
    client, db, bootstrap_source, credit_roles, williams_entity
):
    """A section's rows are a prefix of its listing — so the People section must keep
    the ``-credit_count, name, pk`` order. This guards the explicit ``order_by`` the
    search builder re-applies (``_person_list_qs`` drops the ``pk`` tiebreak); the
    chosen names sort the opposite way alphabetically, so a result ordered by name
    instead of credit count would fail.
    """
    mm = make_machine_model(
        name="Order Game", slug="order-game", corporate_entity=williams_entity
    )
    design = CreditRole.objects.get(slug="design")
    art = CreditRole.objects.get(slug="art")

    # Names sort the OPPOSITE way to credit count, so a by-name regression fails.
    two = _make_person("Order Zzz", "order-zzz", bootstrap_source)  # 2 credits
    one = _make_person("Order Mmm", "order-mmm", bootstrap_source)  # 1 credit
    _make_person("Order Aaa", "order-aaa", bootstrap_source)  # 0 credits
    Credit.objects.create(model=mm, person=two, role=design)
    Credit.objects.create(model=mm, person=two, role=art)
    Credit.objects.create(model=mm, person=one, role=design)

    names = [
        p["name"]
        for p in client.get("/api/pages/search?q=order").json()["people"]["items"]
    ]
    assert names == ["Order Zzz", "Order Mmm", "Order Aaa"]


def test_query_count_is_constant_across_result_size(
    client, db, bootstrap_source, credit_roles, williams_entity
):
    """N+1 guard: each section batches its rows, related cards and thumbnails, so the
    query count must not grow with the number of matching rows. Rows carry real models,
    manufacturers, credits and media so the card serializers exercise their
    select_related / prefetch / thumbnail paths — a dropped prefetch would surface here
    as a per-row query.
    """
    design = CreditRole.objects.get(slug="design")

    def add_matching_row(i: int) -> None:
        model = make_machine_model(
            name=f"Scale Title {i}",
            slug=f"scale-title-{i}",
            corporate_entity=williams_entity,
            year=1990 + i,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        _make_manufacturer(f"Scale Mfr {i}", f"scale-mfr-{i}", bootstrap_source)
        person = _make_person(
            f"Scale Person {i}", f"scale-person-{i}", bootstrap_source
        )
        Credit.objects.create(model=model, person=person, role=design)

    def query_count() -> int:
        with CaptureQueriesContext(connection) as ctx:
            client.get("/api/pages/search?q=scale")
        return len(ctx)

    add_matching_row(1)
    small = query_count()

    for i in range(2, 9):
        add_matching_row(i)
    large = query_count()

    assert small == large


# ---------------------------------------------------------------------------
# Description tier (global search only)
# ---------------------------------------------------------------------------


def test_description_only_match_surfaces_in_each_section(client, db, bootstrap_source):
    """A row whose ``name`` does NOT contain the term but whose ``description`` does
    still appears in its section — the ``DescribedModel`` tier, applied uniformly to
    every describable entity in global search."""
    Title.objects.create(
        name="Bright Star",
        slug="bright-star",
        description="A cabinet with xylophone art.",
    )
    _make_manufacturer(
        "Acme Corp",
        "acme-corp",
        bootstrap_source,
        description="Builds xylophone machines.",
    )
    _make_person(
        "Jane Doe",
        "jane-doe",
        bootstrap_source,
        description="Designed the xylophone ramp.",
    )

    data = client.get("/api/pages/search?q=xylophone").json()
    assert [t["name"] for t in data["titles"]["items"]] == ["Bright Star"]
    assert [m["name"] for m in data["manufacturers"]["items"]] == ["Acme Corp"]
    assert [p["name"] for p in data["people"]["items"]] == ["Jane Doe"]


def test_name_matches_rank_above_description_matches(client, db, williams_entity):
    """Tiering: a name match precedes a description-only match even when the
    description match would otherwise sort first. The name-tier title is older, so a
    single ``latest_year``-ordered query (tiering broken) would rank the newer
    description-only title first — this pins the two-tier ordering."""
    zeta = Title.objects.create(name="Zeta Classic", slug="zeta-classic")
    make_machine_model(
        title=zeta, name="Zeta Classic", slug="zeta-classic-m", year=1985
    )
    retro = Title.objects.create(
        name="Retro Blast",
        slug="retro-blast",
        description="Includes a zeta bonus mode.",
    )
    make_machine_model(title=retro, name="Retro Blast", slug="retro-blast-m", year=2020)

    names = [
        t["name"]
        for t in client.get("/api/pages/search?q=zeta").json()["titles"]["items"]
    ]
    assert names == ["Zeta Classic", "Retro Blast"]


def test_has_more_counts_name_and_description_combined(client, db, bootstrap_source):
    """``has_more`` reflects both tiers: a section under 11 name matches but over 11
    combined (name + description) still reports more."""
    for i in range(6):
        _make_manufacturer(f"Combo {i}", f"combo-name-{i}", bootstrap_source)
    for i in range(6):
        _make_manufacturer(
            f"Filler {i}",
            f"combo-desc-{i}",
            bootstrap_source,
            description="a combo maker",
        )

    section = client.get("/api/pages/search?q=combo").json()["manufacturers"]
    assert len(section["items"]) == 10
    assert section["has_more"] is True
    # Name-tier rows come first; a description-only row fills a remaining slot.
    names = [m["name"] for m in section["items"]]
    assert names[:6] == [f"Combo {i}" for i in range(6)]
    assert any(n.startswith("Filler") for n in names)


def test_description_match_does_not_feed_the_create_gate(client, db, bootstrap_source):
    """The core constraint: a description-only match is surfaced by global search but
    must NOT count toward the listing endpoints' ``query_count`` — otherwise the
    "create this record?" prompt would wrongly vanish for a name that is still free."""
    Title.objects.create(
        name="Blank Slate", slug="blank-slate", description="mentions a widget"
    )
    _make_manufacturer(
        "Empty Co", "empty-co", bootstrap_source, description="assembles a widget"
    )

    # Global search DOES surface them (description tier)…
    search = client.get("/api/pages/search?q=widget").json()
    assert [t["name"] for t in search["titles"]["items"]] == ["Blank Slate"]
    assert [m["name"] for m in search["manufacturers"]["items"]] == ["Empty Co"]

    # …but the record-creation gate stays blind, so the prompt still fires.
    assert client.get("/api/pages/titles?q=widget").json()["query_count"] == 0
    assert client.get("/api/pages/manufacturers?q=widget").json()["query_count"] == 0
