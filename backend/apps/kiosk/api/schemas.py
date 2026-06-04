"""Schemas for the kiosk resource API and page API."""

from __future__ import annotations

from ninja import Schema

from apps.catalog.api.schemas import EntityRef

# ── Resource API (superuser CRUD) ─────────────────────────────────────


class KioskConfigItemInputSchema(Schema):
    """One item in a PATCH payload — the title is referenced by slug."""

    title_slug: str
    hook: str = ""
    position: int


class KioskConfigPatchSchema(Schema):
    """Partial-update payload. Items, when present, fully replace the list."""

    page_heading: str | None = None
    idle_seconds: int | None = None
    items: list[KioskConfigItemInputSchema] | None = None


class KioskConfigItemTitleSchema(Schema):
    """Title shape for the editor — identity plus the manufacturer + year the
    editor renders beside each configured row. ``manufacturer``/``year`` are
    derived live from the title's first model (not stored on the item), exactly
    as the display page derives them; see ``apps.kiosk.api._titles``."""

    public_id: str
    name: str
    manufacturer: EntityRef | None = None
    year: int | None = None


class KioskConfigItemDetailSchema(Schema):
    """One item in the detail response — title carries enough to render the editor."""

    id: int
    position: int
    hook: str
    title: KioskConfigItemTitleSchema


class KioskConfigDetailSchema(Schema):
    """Full configuration as returned by GET/POST/PATCH on the resource API."""

    id: int
    page_heading: str
    idle_seconds: int
    items: list[KioskConfigItemDetailSchema]


class KioskConfigListItemSchema(Schema):
    """One row in the list view."""

    id: int
    page_heading: str
    idle_seconds: int
    item_count: int


# ── Page API (public, anon-allowed) ───────────────────────────────────


class KioskItemTitleSchema(Schema):
    """Subset of TitleListItemSchema needed by the kiosk display."""

    slug: str
    name: str
    thumbnail_url: str | None = None
    manufacturer: EntityRef | None = None
    year: int | None = None


class KioskPageItemSchema(Schema):
    position: int
    hook: str
    title: KioskItemTitleSchema


class KioskPageSchema(Schema):
    id: int
    page_heading: str
    idle_seconds: int
    items: list[KioskPageItemSchema]
