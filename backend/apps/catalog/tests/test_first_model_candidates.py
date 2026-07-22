"""The "first model" (primary-model) rule: which of a Title's models stands in
for the Title on the detail page, search sublabels and facets.

Single-sourced in :meth:`MachineModel.first_model_candidates`. A Title's
representative model must be an original, never a subordinate copy of a sibling
(variant, bootleg or licensed build) — otherwise e.g. the Big Ben Title picks
its Segasa licensed build over the Williams original.
"""

import pytest

from apps.catalog.models import (
    LicenseStatus,
    MachineModel,
    ModelRelationship,
    RelationshipType,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model


@pytest.fixture
def big_ben_title(db) -> Title:
    return Title.objects.create(slug="big-ben-1975", name="Big Ben")


def _candidates(title: Title) -> list[MachineModel]:
    """The Title's first-model candidates in rule order (no extra ordering)."""
    return list(MachineModel.first_model_candidates().filter(title=title))


def _first_model(title: Title) -> MachineModel | None:
    return next(iter(_candidates(title)), None)


# In each case the derivative is given an earlier ``year`` than the original, so
# it would win the ``(year, name)`` sort — only the lineage-field exclusion, not
# the ordering, can keep the original as the Title's first model.


@pytest.mark.django_db
def test_variant_sibling_is_not_the_first_model(big_ben_title):
    original = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-le", year=1975
    )
    make_machine_model(
        title=big_ben_title,
        name="Big Ben Deluxe",
        slug="big-ben-deluxe",
        year=1974,
        variant_of=original,
    )
    assert _first_model(big_ben_title) == original


@pytest.mark.django_db
def test_remake_stays_eligible(db):
    """A remake is a distinct product, not a subordinate copy: a Title whose
    only model is a remake must still surface it as the first model."""
    remake = make_machine_model(name="Remade Thing", slug="remade-thing", year=2018)
    original = make_machine_model(name="Old Thing", slug="old-thing", year=1979)
    remake.remake_of = original
    remake.save(update_fields=["remake_of"])
    assert _first_model(remake.title) == remake


# ── ModelRelationship subordinating edges ────────────────────────────
#
# A subordinating edge (per RELATIONSHIP_TYPE_BEHAVIOR — today copy and
# retheme) is what demotes a model below the original when picking a Title's
# representative — the Big Ben rule. The legacy lineage FKs are gone; edges
# are the only read.


@pytest.mark.django_db
def test_copy_edge_sibling_is_not_the_first_model(big_ben_title):
    """A copy edge (no legacy FK) subordinates exactly like bootleg_of did."""
    original = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-williams", year=1975
    )
    copy = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-segasa", year=1974
    )
    ModelRelationship.objects.create(
        machine_model=copy,
        target_machine=original,
        relationship_type=RelationshipType.COPY,
        license_status=LicenseStatus.LICENSED,
    )
    assert _first_model(big_ben_title) == original
    assert set(_candidates(big_ben_title)) == {original, copy}


@pytest.mark.django_db
def test_label_target_copy_edge_still_subordinates(big_ben_title):
    """A copy is subordinate even when its target isn't seeded (label rung)."""
    original = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-williams", year=1975
    )
    copy = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-petaco", year=1974
    )
    ModelRelationship.objects.create(
        machine_model=copy,
        target_label="an unidentified Williams game",
        relationship_type=RelationshipType.COPY,
    )
    assert _first_model(big_ben_title) == original


@pytest.mark.django_db
def test_retheme_edge_sibling_is_not_the_first_model(big_ben_title):
    """A re-theme sharing its donor's Title never heads it — the donor is the
    original. Not hypothetical: Metallica (Retheme) sits under the Earthshaker
    Title with its donor.

    The re-theme is given the *earlier* year so the ``(year, name)`` tiebreak
    would pick it if subordination weren't doing the work — a donor is
    necessarily older in reality, so only an inverted year proves the rule
    rather than the tiebreak.
    """
    original = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-williams", year=1975
    )
    retheme = make_machine_model(
        title=big_ben_title, name="Big Ben Reskinned", slug="big-ben-reskin", year=1974
    )
    ModelRelationship.objects.create(
        machine_model=retheme,
        target_machine=original,
        relationship_type=RelationshipType.RETHEME,
    )
    assert _first_model(big_ben_title) == original
    assert set(_candidates(big_ben_title)) == {original, retheme}


@pytest.mark.django_db
def test_undated_retheme_still_loses_to_its_dated_donor(big_ben_title):
    """The year tiebreak can't be leaned on: an undated re-theme would sort
    ahead of its dated donor (NULLs sort first on SQLite), so subordination is
    what keeps the original at the head."""
    original = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-williams", year=1975
    )
    retheme = make_machine_model(
        title=big_ben_title, name="Big Ben Reskinned", slug="big-ben-reskin", year=None
    )
    ModelRelationship.objects.create(
        machine_model=retheme,
        target_machine=original,
        relationship_type=RelationshipType.RETHEME,
    )
    assert _first_model(big_ben_title) == original


@pytest.mark.django_db
def test_conversion_edge_stays_eligible(db):
    """Conversion/kit edges are originals in their own right — they don't
    subordinate, unlike copy and re-theme edges."""
    donor = make_machine_model(name="Base Game", slug="base-game", year=1990)
    conversion = make_machine_model(
        name="Converted Game", slug="converted-game", year=1991
    )
    ModelRelationship.objects.create(
        machine_model=conversion,
        target_machine=donor,
        relationship_type=RelationshipType.CONVERSION,
    )
    assert _first_model(conversion.title) == conversion


@pytest.mark.django_db
def test_copy_edge_only_title_still_surfaces_the_copy(db):
    """A Title whose only model carries a copy edge still surfaces it."""
    us_model = make_machine_model(name="Party Animal", slug="party-animal-us")
    de_only = make_machine_model(name="Party Animal", slug="party-animal-de")
    ModelRelationship.objects.create(
        machine_model=de_only,
        target_machine=us_model,
        relationship_type=RelationshipType.COPY,
        license_status=LicenseStatus.LICENSED,
    )
    assert _first_model(de_only.title) == de_only


def test_every_relationship_type_classifies_its_behavior() -> None:
    """The forcing function for new relationship types: every enum value must
    carry an explicit behavior entry (the ``RelationshipTypeBehavior``
    constructor then requires each decision — ``subordinates``,
    ``requires_machine_target``), so a new type (e.g. retheme) cannot silently
    inherit a default."""
    from apps.catalog.models.model_relationship import (
        RELATIONSHIP_TYPE_BEHAVIOR,
        RelationshipType,
    )

    unclassified = set(RelationshipType) - set(RELATIONSHIP_TYPE_BEHAVIOR)
    assert not unclassified, (
        f"RelationshipType value(s) {sorted(t.value for t in unclassified)} have "
        "no RELATIONSHIP_TYPE_BEHAVIOR entry — decide its subordination (the Big "
        "Ben rule) and whether it requires a seeded machine target."
    )


# ── export_edition_of subordination ──────────────────────────────────


@pytest.mark.django_db
def test_export_edition_sibling_is_not_the_first_model(big_ben_title):
    """An export edition sharing a Title with its domestic original never heads
    it (Exports.md). Same-year pairs are the common real case (the export ships
    the same year), so the ``(year, name)`` tiebreak can't be trusted — here the
    export is given the *earlier* year to prove subordination does the work."""
    domestic = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-domestic", year=1975
    )
    export = make_machine_model(
        title=big_ben_title, name="Big Ben (Italy)", slug="big-ben-italy", year=1974
    )
    export.export_edition_of = domestic
    export.save(update_fields=["export_edition_of"])
    assert _first_model(big_ben_title) == domestic
    assert set(_candidates(big_ben_title)) == {domestic, export}


@pytest.mark.django_db
def test_export_edition_only_title_still_surfaces_it(db):
    """Subordination is a tiebreak against originals, not a bar: a Title whose
    only model is an export edition still surfaces it."""
    domestic = make_machine_model(name="Dragoon", slug="dragoon", year=1977)
    export = make_machine_model(name="Dragon", slug="dragon-interflip", year=1977)
    export.export_edition_of = domestic
    export.save(update_fields=["export_edition_of"])
    assert _first_model(export.title) == export
