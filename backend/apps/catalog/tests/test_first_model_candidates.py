"""The "first model" (primary-model) rule: which of a Title's models stands in
for the Title on the detail page, search sublabels and facets.

Single-sourced in :meth:`MachineModel.first_model_candidates`. A Title's
representative model must be an original, never a subordinate copy of a sibling
(variant, bootleg or licensed build) — otherwise e.g. the Big Ben Title picks
its Segasa licensed build over the Williams original.
"""

import pytest

from apps.catalog.models import MachineModel, Title
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
def test_bootleg_sibling_is_not_the_first_model(big_ben_title):
    """A bootleg that outsorts the original must not be chosen over it, but is
    still listed among the Title's models."""
    original = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-williams", year=1975
    )
    copy = make_machine_model(
        title=big_ben_title,
        name="Big Ben",
        slug="big-ben-segasa",
        year=1974,
        bootleg_of=original,
    )
    assert _first_model(big_ben_title) == original
    assert set(_candidates(big_ben_title)) == {original, copy}


@pytest.mark.django_db
def test_licensed_build_sibling_is_not_the_first_model(big_ben_title):
    """A licensed build that outsorts the original must not be chosen."""
    original = make_machine_model(
        title=big_ben_title, name="Big Ben", slug="big-ben-williams", year=1975
    )
    make_machine_model(
        title=big_ben_title,
        name="Big Ben",
        slug="big-ben-segasa",
        year=1974,
        licensed_build_of=original,
    )
    assert _first_model(big_ben_title) == original


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
def test_copy_only_title_still_surfaces_the_copy(db):
    """A Title whose only model is a licensed build (its original lives under a
    different Title) still surfaces that copy as its first model — the copy is
    sorted last, not filtered out."""
    us_model = make_machine_model(name="Party Animal", slug="party-animal-us")
    de_only = make_machine_model(
        name="Party Animal", slug="party-animal-de", licensed_build_of=us_model
    )
    assert _first_model(de_only.title) == de_only


@pytest.mark.django_db
def test_remake_stays_eligible(db):
    """A remake is a distinct product, not a subordinate copy: a Title whose
    only model is a remake must still surface it as the first model."""
    remake = make_machine_model(name="Remade Thing", slug="remade-thing", year=2018)
    original = make_machine_model(name="Old Thing", slug="old-thing", year=1979)
    remake.remake_of = original
    remake.save(update_fields=["remake_of"])
    assert _first_model(remake.title) == remake


@pytest.mark.django_db
def test_conversion_stays_eligible(db):
    """A conversion is a genuinely different machine, so it remains eligible."""
    source = make_machine_model(name="Base Game", slug="base-game", year=1990)
    conversion = make_machine_model(name="Retheme", slug="retheme", year=1991)
    conversion.converted_from = source
    conversion.save(update_fields=["converted_from"])
    assert _first_model(conversion.title) == conversion
