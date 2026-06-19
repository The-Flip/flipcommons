"""Helpers for computing Location paths and deriving child location types.

Location is the only catalog entity whose URL identity is multi-segment
(``location_path = "usa/il/chicago"``) and whose child type is implicit
in its parent's ``divisions`` list. These helpers centralize the two
derivations so the create routes, the read serializer, and the test
suite all agree on one rule.
"""

from __future__ import annotations

from collections.abc import Sequence

from apps.catalog.models import Location
from apps.core.exceptions import StructuredValidationError

__all__ = [
    "compute_location_path",
    "derive_child_location_type",
    "lookup_child_division",
]


def lookup_child_division(
    divisions: Sequence[str] | None, parent_depth: int
) -> str | None:
    """Return ``divisions[parent_depth]`` if in range, else ``None``.

    Single source of truth for "what label does the next tier carry?".
    Both the read serializer (which wants ``None`` to suppress
    "+ New …") and :func:`derive_child_location_type` (which wants to
    raise on the same conditions) call this. Read-side gets ``None``
    directly; create-side translates ``None`` into a structured 422
    distinguishing missing-divisions from too-deep-tree.
    """
    if not divisions or parent_depth >= len(divisions):
        return None
    return divisions[parent_depth]


def compute_location_path(parent: Location | None, slug: str) -> str:
    """Return the new row's ``location_path`` from *parent* and *slug*.

    Instance-based wrapper over :meth:`Location.compose_public_id` (the single
    home of the ``parent_path + "/" + slug`` formula) for the write API, which
    holds a parent row rather than its path. Top-level countries have no
    parent, so the path is just the slug.
    """
    parent_path = parent.location_path if parent is not None else None
    return Location.compose_public_id({"slug": slug, "parent": parent_path})


def _country_ancestor(location: Location) -> Location:
    """Walk up the parent chain to the country (root) ancestor.

    Callers that hit this in a hot loop should prefetch the parent
    chain via ``select_related("parent__parent__…")``.
    """
    cur = location
    # Pindata's declared max depth is 4; the bound here is a safety
    # break against malformed data that would otherwise silently issue
    # extra DB hits per ``cur.parent`` dereference.
    for _ in range(10):
        if cur.parent_id is None:
            return cur
        cur = cur.parent  # type: ignore[assignment]
    raise RuntimeError(
        f"Location {location.location_path!r} has a parent chain deeper "
        "than 10; data is malformed."
    )


def derive_child_location_type(parent: Location) -> str:
    """Return the location_type a new direct child of *parent* should have.

    Walks from *parent* up to the country ancestor, then indexes that
    country's ``divisions`` list by the parent's depth (number of
    slashes in the parent's path). A country with
    ``divisions=["state", "city"]`` produces ``"state"`` for direct
    children and ``"city"`` for grandchildren.

    Raises :class:`StructuredValidationError` with a form-level message
    when the country ancestor declares no divisions or when the tree is
    deeper than the declared division levels. ``form_errors`` (not
    ``field_errors``): this is a structural problem with the parent
    tree, not an error on a specific input field the user typed.
    """
    country = _country_ancestor(parent)
    divisions = country.divisions
    parent_depth = parent.location_path.count("/")

    result = lookup_child_division(divisions, parent_depth)
    if result is not None:
        return result

    if not divisions:
        message = (
            f"Country '{country.name}' has no divisions declared; cannot "
            "create child locations under it. Edit the country and add "
            "divisions first."
        )
    else:
        labels = ", ".join(divisions)
        message = (
            f"Country '{country.name}' declares {len(divisions)} division "
            f"level(s) ({labels}); cannot create a level-{parent_depth + 1} "
            f"child under '{parent.location_path}'."
        )
    raise StructuredValidationError(message=message, form_errors=[message])
