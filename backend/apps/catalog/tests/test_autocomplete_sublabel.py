"""Unit tests for the shared ``manufacturer_year_sublabel`` formatter.

Both ``Title`` and ``MachineModel`` feed it a (manufacturer, year) pair where
either part can be missing — a model with a year but no corporate entity, a
title whose first model has no year, etc. — so all four branches are reachable.
"""

from __future__ import annotations

import pytest

from apps.catalog.models._autocomplete import manufacturer_year_sublabel


@pytest.mark.parametrize(
    ("manufacturer_name", "year", "expected"),
    [
        ("Williams", 1997, "Williams · 1997"),
        ("Williams", None, "Williams"),
        (None, 1997, "1997"),
        (None, None, None),
    ],
)
def test_manufacturer_year_sublabel(manufacturer_name, year, expected):
    assert manufacturer_year_sublabel(manufacturer_name, year) == expected
