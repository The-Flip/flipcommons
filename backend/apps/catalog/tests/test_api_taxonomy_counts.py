"""Tests for ``title_count`` across taxonomy list endpoints.

Covers the three branches of the count contract:
  - Hierarchical taxonomies (gameplay-feature, theme): rollup with dedup.
  - Flat model-attached taxonomies (cabinet representative): direct count.
  - credit-role: schema split — no ``title_count`` field at all.

Filter invariants assert that variants, soft-deleted models, and
soft-deleted titles are excluded from every count.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import (
    Cabinet,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    GameplayFeature,
    MachineModel,
    Manufacturer,
    System,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    Title,
)
from apps.core.models import EntityStatus


def _title(name: str, slug: str | None = None, *, status: str | None = None) -> Title:
    t = Title.objects.create(name=name, slug=slug or name.lower().replace(" ", "-"))
    if status is not None:
        t.status = status
        t.save(update_fields=["status"])
    return t


def _model(
    title: Title,
    name: str,
    *,
    variant_of: MachineModel | None = None,
    status: str | None = None,
) -> MachineModel:
    mm = MachineModel.objects.create(
        title=title,
        name=name,
        slug=name.lower().replace(" ", "-"),
        variant_of=variant_of,
    )
    if status is not None:
        mm.status = status
        mm.save(update_fields=["status"])
    return mm


def _assign_and_save(obj, **fields) -> None:
    for field_name, value in fields.items():
        setattr(obj, field_name, value)
    obj.save(update_fields=list(fields))


# ---------------------------------------------------------------------------
# gameplay-features: hierarchy + rollup + dedup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGameplayFeatureTitleCount:
    def test_field_is_title_count_not_model_count(self, client):
        GameplayFeature.objects.create(name="Multiball", slug="multiball")
        resp = client.get("/api/gameplay-features/")
        assert resp.status_code == 200
        body = resp.json()["items"]
        assert "title_count" in body[0]
        assert "model_count" not in body[0]

    def test_distinct_titles_not_models(self, client):
        # One title with two non-variant models attached to the feature should
        # produce title_count=1, proving we count titles (not models).
        gf = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        title = _title("Funhouse")
        m1 = _model(title, "Funhouse A")
        m2 = _model(title, "Funhouse B")
        m1.gameplay_features.add(gf)
        m2.gameplay_features.add(gf)
        resp = client.get("/api/gameplay-features/")
        row = next(r for r in resp.json()["items"] if r["slug"] == "multiball")
        assert row["title_count"] == 1

    def test_variants_excluded(self, client):
        gf = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        title = _title("Funhouse")
        primary = _model(title, "Funhouse")
        variant = _model(title, "Funhouse Variant", variant_of=primary)
        # Attach feature only to the variant; primary is not tagged.
        variant.gameplay_features.add(gf)
        resp = client.get("/api/gameplay-features/")
        row = next(r for r in resp.json()["items"] if r["slug"] == "multiball")
        # Variant doesn't count → no titles reach the feature.
        assert row["title_count"] == 0

    def test_inactive_models_excluded(self, client):
        gf = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        title = _title("Funhouse")
        m = _model(title, "Funhouse", status=EntityStatus.DELETED)
        m.gameplay_features.add(gf)
        resp = client.get("/api/gameplay-features/")
        row = next(r for r in resp.json()["items"] if r["slug"] == "multiball")
        assert row["title_count"] == 0

    def test_inactive_titles_excluded(self, client):
        gf = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        title = _title("Funhouse", status=EntityStatus.DELETED)
        m = _model(title, "Funhouse")
        m.gameplay_features.add(gf)
        resp = client.get("/api/gameplay-features/")
        row = next(r for r in resp.json()["items"] if r["slug"] == "multiball")
        assert row["title_count"] == 0

    def test_rollup_unions_descendants(self, client):
        # parent ── child_a (title A)
        #        └─ child_b (title B)
        # parent should roll up to title_count=2.
        parent = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        child_a = GameplayFeature.objects.create(name="2-Ball", slug="two-ball")
        child_b = GameplayFeature.objects.create(name="3-Ball", slug="three-ball")
        child_a.parents.add(parent)
        child_b.parents.add(parent)

        title_a = _title("Game A")
        title_b = _title("Game B")
        _model(title_a, "Game A").gameplay_features.add(child_a)
        _model(title_b, "Game B").gameplay_features.add(child_b)

        rows = {
            r["slug"]: r for r in client.get("/api/gameplay-features/").json()["items"]
        }
        assert rows["two-ball"]["title_count"] == 1
        assert rows["three-ball"]["title_count"] == 1
        assert rows["multiball"]["title_count"] == 2

    def test_rollup_dedups_overlapping_descendants(self, client):
        # parent ── child_a (title A)
        #        └─ child_b (title A)  ← same title
        # parent_count = 1 (union, not sum).
        parent = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        child_a = GameplayFeature.objects.create(name="2-Ball", slug="two-ball")
        child_b = GameplayFeature.objects.create(name="3-Ball", slug="three-ball")
        child_a.parents.add(parent)
        child_b.parents.add(parent)

        title = _title("Shared Game")
        m = _model(title, "Shared Game")
        m.gameplay_features.add(child_a)
        m.gameplay_features.add(child_b)

        rows = {
            r["slug"]: r for r in client.get("/api/gameplay-features/").json()["items"]
        }
        child_sum = rows["two-ball"]["title_count"] + rows["three-ball"]["title_count"]
        # Parent <= sum (overlap reduces); strict < proves dedup.
        assert rows["multiball"]["title_count"] < child_sum
        assert rows["multiball"]["title_count"] == 1
        # Parent >= max(children) — every child's title set is subset of parent.
        assert rows["multiball"]["title_count"] >= max(
            rows["two-ball"]["title_count"], rows["three-ball"]["title_count"]
        )


# ---------------------------------------------------------------------------
# themes: hierarchy + rollup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestThemeTitleCount:
    def test_list_includes_title_count(self, client):
        Theme.objects.create(name="Medieval", slug="medieval")
        resp = client.get("/api/themes/")
        assert resp.status_code == 200
        assert "title_count" in resp.json()["items"][0]

    def test_rollup_with_overlap(self, client):
        parent = Theme.objects.create(name="Fantasy", slug="fantasy")
        child = Theme.objects.create(name="Medieval", slug="medieval")
        child.parents.add(parent)

        title = _title("Medieval Madness")
        m = _model(title, "Medieval Madness")
        m.themes.add(child)
        m.themes.add(parent)  # title is on parent directly too

        rows = {r["slug"]: r for r in client.get("/api/themes/").json()["items"]}
        # Parent rollup = union(direct={title}, child's titles={title}) = 1.
        assert rows["fantasy"]["title_count"] == 1
        assert rows["medieval"]["title_count"] == 1


# ---------------------------------------------------------------------------
# Flat model-attached taxonomy (cabinet as representative)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFlatTaxonomyTitleCount:
    def test_cabinet_list_includes_title_count(self, client):
        cab = Cabinet.objects.create(name="Floor", slug="floor", display_order=1)
        title = _title("Funhouse")
        m = _model(title, "Funhouse")
        _assign_and_save(m, cabinet=cab)

        rows = {r["slug"]: r for r in client.get("/api/cabinets/").json()["items"]}
        assert rows["floor"]["title_count"] == 1

    def test_cabinet_excludes_variants_and_inactives(self, client):
        cab = Cabinet.objects.create(name="Floor", slug="floor", display_order=1)
        title = _title("Funhouse")
        primary = _model(title, "Funhouse")
        _assign_and_save(primary, cabinet=cab)
        # Variant of primary, also tagged with cabinet — should not double-count.
        v = _model(title, "Funhouse Variant", variant_of=primary)
        _assign_and_save(v, cabinet=cab)
        # A deleted model on a different title — should not contribute.
        other = _title("Other Game")
        m = _model(other, "Other", status=EntityStatus.DELETED)
        _assign_and_save(m, cabinet=cab)

        rows = {r["slug"]: r for r in client.get("/api/cabinets/").json()["items"]}
        assert rows["floor"]["title_count"] == 1


# ---------------------------------------------------------------------------
# credit-role: schema split — no title_count field
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreditRoleNoCount:
    def test_credit_role_list_omits_title_count(self, client):
        CreditRole.objects.create(name="Design", slug="design", display_order=10)
        resp = client.get("/api/credit-roles/")
        assert resp.status_code == 200
        body = resp.json()["items"]
        assert body, "expected at least one credit role"
        assert "title_count" not in body[0]


# ---------------------------------------------------------------------------
# display-types: nested subtypes with their own title_count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDisplayTypesNestedSubtypes:
    """The display-types list endpoint nests subtypes under each type.

    ``/display-subtypes/`` has no list endpoint — subtypes are exposed only
    through their parent type. Tests cover:
      - response shape (subtypes present on every type, empty list allowed),
      - sort order (types and subtypes both by display_order),
      - title counts on both tiers,
      - soft-deleted subtypes excluded.
    """

    def test_subtypes_nested_under_parent_type(self, client):
        lcd = DisplayType.objects.create(name="LCD", slug="lcd", display_order=4)
        dmd = DisplayType.objects.create(
            name="Dot Matrix", slug="dot-matrix", display_order=3
        )
        DisplaySubtype.objects.create(
            name="HD LCD", slug="hd-lcd", display_type=lcd, display_order=2
        )
        DisplaySubtype.objects.create(
            name="Standard LCD", slug="standard-lcd", display_type=lcd, display_order=1
        )
        DisplaySubtype.objects.create(
            name="Plasma DMD",
            slug="plasma-dmd",
            display_type=dmd,
            display_order=1,
        )

        resp = client.get("/api/display-types/")
        assert resp.status_code == 200
        body = resp.json()

        rows = {r["slug"]: r for r in body}
        assert [s["slug"] for s in rows["lcd"]["subtypes"]] == [
            "standard-lcd",
            "hd-lcd",
        ]
        assert [s["slug"] for s in rows["dot-matrix"]["subtypes"]] == ["plasma-dmd"]

    def test_types_sorted_by_display_order(self, client):
        DisplayType.objects.create(name="LCD", slug="lcd", display_order=4)
        DisplayType.objects.create(
            name="Dot Matrix", slug="dot-matrix", display_order=3
        )
        DisplayType.objects.create(
            name="Score Reels", slug="score-reels", display_order=1
        )

        body = client.get("/api/display-types/").json()
        assert [r["slug"] for r in body] == ["score-reels", "dot-matrix", "lcd"]

    def test_type_with_no_subtypes_returns_empty_list(self, client):
        DisplayType.objects.create(
            name="Backglass Lights", slug="backglass-lights", display_order=1
        )

        body = client.get("/api/display-types/").json()
        assert body[0]["subtypes"] == []

    def test_soft_deleted_subtype_excluded(self, client):
        lcd = DisplayType.objects.create(name="LCD", slug="lcd", display_order=1)
        DisplaySubtype.objects.create(
            name="HD LCD", slug="hd-lcd", display_type=lcd, display_order=1
        )
        DisplaySubtype.objects.create(
            name="Retired LCD",
            slug="retired-lcd",
            display_type=lcd,
            display_order=2,
            status=EntityStatus.DELETED,
        )

        body = client.get("/api/display-types/").json()
        slugs = [s["slug"] for s in body[0]["subtypes"]]
        assert slugs == ["hd-lcd"]

    def test_title_count_populated_on_both_tiers(self, client):
        lcd = DisplayType.objects.create(name="LCD", slug="lcd", display_order=1)
        hd = DisplaySubtype.objects.create(
            name="HD LCD", slug="hd-lcd", display_type=lcd, display_order=1
        )
        title = _title("Wizard of Oz")
        mm = _model(title, "Wizard of Oz")
        _assign_and_save(mm, display_type=lcd, display_subtype=hd)

        body = client.get("/api/display-types/").json()
        row = next(r for r in body if r["slug"] == "lcd")
        assert row["title_count"] == 1
        assert row["subtypes"][0]["title_count"] == 1


# ---------------------------------------------------------------------------
# technology-generations: nested subgenerations with their own title_count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTechnologyGenerationsNestedSubgenerations:
    """Mirrors ``TestDisplayTypesNestedSubtypes`` for the
    technology-generations endpoint. ``/technology-subgenerations/`` has
    no list endpoint — subgenerations are exposed only through their
    parent generation.
    """

    def test_subgenerations_nested_under_parent_generation(self, client):
        ss = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", display_order=3
        )
        em = TechnologyGeneration.objects.create(
            name="Electromechanical", slug="electromechanical", display_order=2
        )
        TechnologySubgeneration.objects.create(
            name="Integrated MPU",
            slug="integrated-mpu",
            technology_generation=ss,
            display_order=2,
        )
        TechnologySubgeneration.objects.create(
            name="Discrete Logic",
            slug="discrete-logic",
            technology_generation=ss,
            display_order=1,
        )
        TechnologySubgeneration.objects.create(
            name="Pre-Flipper EM",
            slug="pre-flipper-em",
            technology_generation=em,
            display_order=1,
        )

        body = client.get("/api/technology-generations/").json()
        rows = {r["slug"]: r for r in body}
        assert [s["slug"] for s in rows["solid-state"]["subgenerations"]] == [
            "discrete-logic",
            "integrated-mpu",
        ]
        assert [s["slug"] for s in rows["electromechanical"]["subgenerations"]] == [
            "pre-flipper-em"
        ]

    def test_generations_sorted_by_display_order(self, client):
        TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", display_order=3
        )
        TechnologyGeneration.objects.create(
            name="Pure Mechanical", slug="pure-mechanical", display_order=1
        )
        TechnologyGeneration.objects.create(
            name="Electromechanical", slug="electromechanical", display_order=2
        )

        body = client.get("/api/technology-generations/").json()
        assert [r["slug"] for r in body] == [
            "pure-mechanical",
            "electromechanical",
            "solid-state",
        ]

    def test_generation_with_no_subgenerations_returns_empty_list(self, client):
        TechnologyGeneration.objects.create(
            name="Pure Mechanical", slug="pure-mechanical", display_order=1
        )

        body = client.get("/api/technology-generations/").json()
        assert body[0]["subgenerations"] == []

    def test_soft_deleted_subgeneration_excluded(self, client):
        ss = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", display_order=1
        )
        TechnologySubgeneration.objects.create(
            name="Integrated MPU",
            slug="integrated-mpu",
            technology_generation=ss,
            display_order=1,
        )
        TechnologySubgeneration.objects.create(
            name="Retired Subgen",
            slug="retired-subgen",
            technology_generation=ss,
            display_order=2,
            status=EntityStatus.DELETED,
        )

        body = client.get("/api/technology-generations/").json()
        slugs = [s["slug"] for s in body[0]["subgenerations"]]
        assert slugs == ["integrated-mpu"]

    def test_title_count_populated_on_both_tiers(self, client):
        ss = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", display_order=1
        )
        mpu = TechnologySubgeneration.objects.create(
            name="Integrated MPU",
            slug="integrated-mpu",
            technology_generation=ss,
            display_order=1,
        )
        title = _title("Funhouse")
        mm = _model(title, "Funhouse")
        _assign_and_save(
            mm,
            technology_generation=ss,
            technology_subgeneration=mpu,
        )

        body = client.get("/api/technology-generations/").json()
        row = next(r for r in body if r["slug"] == "solid-state")
        assert row["title_count"] == 1
        assert row["subgenerations"][0]["title_count"] == 1

    def test_subgeneration_count_includes_titles_inherited_via_system(self, client):
        """A model whose System carries a subgeneration should be counted
        under that subgen, mirroring the click-through filter on
        ``/api/models/?subgeneration=...`` which OR's direct-on-model and
        inherited-via-system. Otherwise, counts on this page disagree with
        what the detail page shows.
        """
        ss = TechnologyGeneration.objects.create(
            name="Solid State", slug="solid-state", display_order=1
        )
        mpu = TechnologySubgeneration.objects.create(
            name="Integrated MPU",
            slug="integrated-mpu",
            technology_generation=ss,
            display_order=1,
        )
        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        system = System.objects.create(
            name="WPC-95",
            slug="wpc-95",
            manufacturer=mfr,
            technology_subgeneration=mpu,
        )
        title = _title("Funhouse")
        mm = _model(title, "Funhouse")
        # Direct FK deliberately left unset — subgen is inherited via system.
        _assign_and_save(mm, system=system)

        body = client.get("/api/technology-generations/").json()
        row = next(r for r in body if r["slug"] == "solid-state")
        assert row["subgenerations"][0]["title_count"] == 1
