"""Shared autocomplete-sublabel helpers for catalog models.

Both ``Title`` and ``MachineModel`` disambiguate same-named rows in typeahead
controls with a "manufacturer · year" second line. The two reach those values
differently — ``MachineModel`` directly (its own ``year`` + ``corporate_entity``
manufacturer), ``Title`` via Subquery annotations over its first non-variant
model — but format them identically, so the formatting lives here.
"""

from __future__ import annotations

# Middle dot separating the manufacturer and year in a sublabel.
_SUBLABEL_SEPARATOR = " · "


def manufacturer_year_sublabel(
    manufacturer_name: str | None, year: int | None
) -> str | None:
    """Format a "manufacturer · year" sublabel from its two parts.

    Drops whichever part is missing; returns ``None`` when both are absent so
    the row carries no sublabel at all rather than an empty separator.
    """
    parts = [
        part
        for part in (manufacturer_name, str(year) if year is not None else None)
        if part
    ]
    return _SUBLABEL_SEPARATOR.join(parts) or None
