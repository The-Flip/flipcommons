"""Meta-test: ensure validator limits match module-level range constants.

If a validator says min=1800 but the constant says YEAR_MIN=1900, the
constraint and validator have drifted. This test catches that.
"""

import pytest
from django.core.validators import MaxValueValidator, MinValueValidator

from apps.catalog.models import (
    CorporateEntity,
    MachineModel,
    Manufacturer,
    Person,
    Title,
)
from apps.catalog.models import gameplay_feature as gf_mod
from apps.catalog.models import machine_model as mm_mod
from apps.catalog.models import manufacturer as mfr_mod
from apps.catalog.models import person as person_mod
from apps.catalog.models import title as title_mod
from apps.catalog.models.gameplay_feature import MachineModelGameplayFeature
from apps.citation import models as citation_mod
from apps.citation.models import CitationSource

# (model_class, field_name, module, min_const_name, max_const_name_or_None)
RANGE_FIELDS = [
    (MachineModel, "year", mm_mod, "YEAR_MIN", "YEAR_MAX"),
    (MachineModel, "month", mm_mod, "MONTH_MIN", "MONTH_MAX"),
    (MachineModel, "player_count", mm_mod, "PLAYER_COUNT_MIN", "PLAYER_COUNT_MAX"),
    (MachineModel, "flipper_count", mm_mod, "FLIPPER_COUNT_MIN", "FLIPPER_COUNT_MAX"),
    (MachineModel, "ipdb_rating", mm_mod, "RATING_MIN", "RATING_MAX"),
    (MachineModel, "pinside_rating", mm_mod, "RATING_MIN", "RATING_MAX"),
    (MachineModel, "ipdb_id", mm_mod, "EXTERNAL_ID_MIN", None),
    (Person, "birth_year", person_mod, "YEAR_MIN", "YEAR_MAX"),
    (Person, "death_year", person_mod, "YEAR_MIN", "YEAR_MAX"),
    (Person, "birth_month", person_mod, "MONTH_MIN", "MONTH_MAX"),
    (Person, "death_month", person_mod, "MONTH_MIN", "MONTH_MAX"),
    (Person, "birth_day", person_mod, "DAY_MIN", "DAY_MAX"),
    (Person, "death_day", person_mod, "DAY_MIN", "DAY_MAX"),
    (CorporateEntity, "year_start", mfr_mod, "YEAR_MIN", "YEAR_MAX"),
    (CorporateEntity, "year_end", mfr_mod, "YEAR_MIN", "YEAR_MAX"),
    (CorporateEntity, "ipdb_manufacturer_id", mfr_mod, "EXTERNAL_ID_MIN", None),
    (Manufacturer, "opdb_manufacturer_id", mfr_mod, "EXTERNAL_ID_MIN", None),
    (Title, "fandom_page_id", title_mod, "EXTERNAL_ID_MIN", None),
    (MachineModelGameplayFeature, "count", gf_mod, "COUNT_MIN", None),
    (CitationSource, "year", citation_mod, "YEAR_MIN", "YEAR_MAX"),
    (CitationSource, "month", citation_mod, "MONTH_MIN", "MONTH_MAX"),
    (CitationSource, "day", citation_mod, "DAY_MIN", "DAY_MAX"),
]


@pytest.mark.parametrize(
    ("model_class", "field_name", "mod", "min_const", "max_const"),
    RANGE_FIELDS,
    ids=[f"{m.__name__}.{f}" for m, f, *_ in RANGE_FIELDS],
)
def test_validator_limits_match_constants(
    model_class, field_name, mod, min_const, max_const
):
    """Verify that field validators reference the same limits as module constants."""
    field = model_class._meta.get_field(field_name)
    expected_min = getattr(mod, min_const)
    expected_max = getattr(mod, max_const) if max_const else None

    found_min = None
    found_max = None
    for v in field._validators:
        if isinstance(v, MinValueValidator):
            found_min = v.limit_value
        elif isinstance(v, MaxValueValidator):
            found_max = v.limit_value

    assert found_min == expected_min, (
        f"{model_class.__name__}.{field_name}: "
        f"MinValueValidator={found_min}, {min_const}={expected_min}"
    )
    if max_const:
        assert found_max == expected_max, (
            f"{model_class.__name__}.{field_name}: "
            f"MaxValueValidator={found_max}, {max_const}={expected_max}"
        )


def test_year_constants_consistent_across_modules():
    """All modules that define YEAR_MIN/YEAR_MAX must agree on the values."""
    modules = {
        "machine_model": mm_mod,
        "person": person_mod,
        "manufacturer": mfr_mod,
        "citation": citation_mod,
    }
    mins = {name: mod.YEAR_MIN for name, mod in modules.items()}
    maxs = {name: mod.YEAR_MAX for name, mod in modules.items()}
    assert len(set(mins.values())) == 1, f"YEAR_MIN values differ: {mins}"
    assert len(set(maxs.values())) == 1, f"YEAR_MAX values differ: {maxs}"
