# Pinball Database — Data Model + Admin + API

## Context

This planning doc predates the February 2026 backend split that replaced
`apps.machines` with `apps.catalog` and `apps.provenance`. The concepts below
are still broadly relevant, but the live implementation now lives in those two
apps rather than a single `backend/apps/machines` module.

Building an interactive pinball database for The Flip museum. Data is coming from many sources, including:

- **Existing online pinball databases**: OPDB, possibly IPDB, and possibly Pinside
- **Editorial contributions from The Flip** (books, research, curatorial notes)
- **Crowdsourcing** (think wikipedia for pinball)

## Data Model Architecture

Two-layer model inspired by CRDTs.

- **Layer 1** is a stream of per-field **claims** from multiple sources.
- **Layer 2** is a **resolved Model** table — a materialized view derived by merging claims with priority-based conflict resolution. The Flip adjudicates conflicts and adds original research with per-fact citations.

## Models (`backend/apps/catalog/models/` and `backend/apps/provenance/models/`)

### Source

Represents a data origin (a database, a book, The Flip's editorial team, etc.).

| Field         | Type                                 | Notes                                                           |
| ------------- | ------------------------------------ | --------------------------------------------------------------- |
| `name`        | CharField(200), unique               | e.g., "IPDB", "Pinball Compendium Vol. 3", "The Flip Editorial" |
| `slug`        | SlugField(200), unique               | Auto-generated                                                  |
| `source_type` | CharField choices                    | `database`, `book`, `editorial`, `other`                        |
| `priority`    | PositiveSmallIntegerField, default=0 | Higher wins conflicts. Editorial sources get highest.           |
| `url`         | URLField, blank                      | e.g., `https://ipdb.org`                                        |
| `description` | TextField, blank                     |                                                                 |

### Claim

A single fact asserted by a single source about a single model. This is the core of the provenance system — the "stream of changes."

| Field        | Type                        | Notes                                                   |
| ------------ | --------------------------- | ------------------------------------------------------- |
| `model`      | FK → PinballModel, CASCADE  | The model this claim is about                           |
| `source`     | FK → Source, PROTECT        | Where this fact came from                               |
| `field_name` | CharField(100)              | Column name on PinballModel or key for `extra_data`     |
| `value`      | JSONField                   | The asserted value (string, number, bool, etc.)         |
| `citation`   | TextField, blank            | "Pinball Compendium Vol. 3, p.47" or IPDB URL           |
| `is_active`  | BooleanField, default=True  | False when superseded by a newer claim from same source |
| `created_at` | DateTimeField, auto_now_add | When this claim was recorded                            |

Indexes: `(model, field_name)`, `(source, model)`, `(field_name, is_active)`.

Unique constraint: `(model, source, field_name, is_active)` filtered to `is_active=True` — at most one active claim per source per field per model. (Use `UniqueConstraint` with `condition`.)

When a source re-asserts a field, the old claim is marked `is_active=False` and a new one is created. This preserves full history.

**Enforced via `ClaimManager.assert_claim(model, source, field_name, value, citation="")`**: A transactional manager method that deactivates the existing active claim (if any) and creates the new one atomically. All write paths must go through this method — no direct `Claim.objects.create()` for production code.

### Manufacturer (brand-level grouping)

User-facing brand. Corporate incarnations are tracked separately in ManufacturerEntity. For example, "Gottlieb" is one Manufacturer with four ManufacturerEntity records spanning different ownership eras.

| Field                  | Type                                   | Notes                                                            |
| ---------------------- | -------------------------------------- | ---------------------------------------------------------------- |
| `name`                 | CharField(200), unique                 | Brand name                                                       |
| `slug`                 | SlugField(200), unique                 | Auto-generated                                                   |
| `trade_name`           | CharField(200), blank                  | Brand name if different (e.g., "Bally" for Midway Manufacturing) |
| `opdb_manufacturer_id` | PositiveIntegerField, unique, nullable | OPDB's manufacturer_id for cross-referencing                     |

### ManufacturerEntity (corporate incarnation)

IPDB tracks corporate entities rather than brands — e.g., four separate entries for Gottlieb across its ownership eras. Each entity maps to one brand-level Manufacturer and carries the IPDB cross-reference ID.

| Field                  | Type                                   | Notes                                              |
| ---------------------- | -------------------------------------- | -------------------------------------------------- |
| `manufacturer`         | FK → Manufacturer, CASCADE             | Parent brand                                       |
| `name`                 | CharField(300)                         | Full corporate name, e.g., "D. Gottlieb & Company" |
| `ipdb_manufacturer_id` | PositiveIntegerField, unique, nullable | IPDB's ManufacturerId for cross-referencing        |
| `years_active`         | CharField(50), blank                   | Operating period, e.g., "1931-1977"                |

### PinballModel (the pinball title/design — the resolved/materialized view)

These fields are **derived** from resolving claims. The resolution logic picks the winning claim per field (highest priority source, most recent if tied).

| Field                 | Type                                   | Notes                                                   |
| --------------------- | -------------------------------------- | ------------------------------------------------------- |
| `name`                | CharField(300)                         | NOT unique (e.g., multiple "Star Trek")                 |
| `slug`                | SlugField(300), unique                 | Disambiguated: `star-trek-bally-1979`                   |
| `ipdb_id`             | PositiveIntegerField, unique, nullable | IPDB cross-reference                                    |
| `opdb_id`             | CharField(50), unique, nullable        | OPDB cross-reference (hierarchical ID)                  |
| `pinside_id`          | PositiveIntegerField, unique, nullable | Pinside cross-reference                                 |
| `manufacturer`        | FK → Manufacturer, nullable            | Browse by manufacturer                                  |
| `year`                | PositiveSmallIntegerField, nullable    | Filter by decade                                        |
| `month`               | PositiveSmallIntegerField, nullable    |                                                         |
| `machine_type`        | CharField choices (PM/EM/SS)           | Filter                                                  |
| `display_type`        | CharField choices, blank               | Score reels, alpha-numeric, DMD, LCD, etc.              |
| `player_count`        | PositiveSmallIntegerField, nullable    |                                                         |
| `theme`               | CharField(300), blank                  |                                                         |
| `production_quantity` | CharField(100), blank                  | Often approximate                                       |
| `mpu`                 | CharField(200), blank                  | Electronic system                                       |
| `flipper_count`       | PositiveSmallIntegerField, nullable    |                                                         |
| `ipdb_rating`         | DecimalField(4,2), nullable            |                                                         |
| `pinside_rating`      | DecimalField(4,2), nullable            |                                                         |
| `educational_text`    | TextField, blank                       | Museum content                                          |
| `sources_notes`       | TextField, blank                       | Editorial                                               |
| `extra_data`          | JSONField, default=dict                | Resolved catch-all for fields without dedicated columns |
| `created_at`          | DateTimeField, auto_now_add            |                                                         |
| `updated_at`          | DateTimeField, auto_now                |                                                         |

Indexes: `(manufacturer, year)`, `(machine_type, year)`, `(display_type)`.

**`extra_data`** (renamed from `ipdb_data`): Holds resolved values for fields that don't have dedicated columns — model_number, abbreviations, playfield features, toys, marketing slogans, weight, msrp, factory address, etc. Any `field_name` in a Claim that doesn't match a column on PinballModel gets resolved into this JSON.

### Person

| Field  | Type                   | Notes                                 |
| ------ | ---------------------- | ------------------------------------- |
| `name` | CharField(200)         | Display name (e.g., "Pat Lawlor")     |
| `slug` | SlugField(200), unique | For URLs: `/people/pat-lawlor`        |
| `bio`  | TextField, blank       | Biographical text (editorial content) |

### DesignCredit

| Field    | Type                       | Notes                                                                     |
| -------- | -------------------------- | ------------------------------------------------------------------------- |
| `model`  | FK → PinballModel, CASCADE |                                                                           |
| `person` | FK → Person, CASCADE       |                                                                           |
| `role`   | CharField choices          | concept, design, art, mechanics, music, sound, software, animation, other |

Unique together: `(model, person, role)`.

The importer splits IPDB's comma-separated credit strings (e.g., `"Larry DeMar, Pat Lawlor"`) into individual Person records via `get_or_create`.

## Resolution logic (`backend/apps/catalog/resolve/` and `backend/apps/provenance/resolution/`)

A `resolve_model(model)` function that:

1. Fetches all active claims for the model, ordered by `field_name`, `-source__priority`, `-created_at`
2. For each field, picks the winning claim (first in that ordering)
3. Maps winning values to PinballModel columns (with type coercion) or `extra_data` keys
4. For `manufacturer` (FK): IPDB sources look up via `ManufacturerEntity.ipdb_manufacturer_id` → parent `Manufacturer`; OPDB sources match on `Manufacturer.opdb_manufacturer_id` directly. Falls back to normalized name lookup. Uses `get_or_create` only after ID-based matching fails.
5. Saves the resolved PinballModel

Also a `resolve_all()` for batch re-resolution after a scrape.

The resolution logic is tested independently in `test_resolve.py`: set up claims from multiple sources with different priorities, verify the resolved PinballModel has the right values.

## Django Admin (`backend/apps/catalog/admin.py` and `backend/apps/provenance/admin.py`)

- **SourceAdmin**: list_display (name, source_type, priority), list_filter (source_type)
- **ClaimAdmin**: list_display (model, field_name, value_truncated, source, is_active, created_at), list_filter (source, is_active, field_name), search (model\_\_name, field_name), readonly created_at. Override `save_model()` to route through `ClaimManager.assert_claim()` so admin creates respect the superseding invariant.
- **ManufacturerAdmin**: list_display (name, trade_name, opdb_manufacturer_id, entity_count), search, prepopulated slug, ManufacturerEntityInline (TabularInline, extra=1)
- **PersonAdmin**: list_display (name, credit_count), search (name), prepopulated slug
- **PinballModelAdmin**: list_display (name, manufacturer, year, machine_type, ipdb_id), list_filter (machine_type, display_type, manufacturer), search (name, ipdb_id, manufacturer\_\_name), fieldsets grouping identity/specs/cross-references/ratings/museum content/extra data (collapsed), DesignCreditInline + ClaimInline (readonly, collapsed — shows provenance per model)
- **DesignCreditInline**: TabularInline on PinballModel, extra=1
- **ClaimInline**: TabularInline on PinballModel, readonly, collapsed, shows active claims with source and citation

## API (`backend/apps/catalog/api/`, `backend/apps/provenance/api.py`, and `backend/config/api.py`)

Routers are now autodiscovered from each app's `api` module via
`backend/config/api.py`. The catalog app exports its routers from
`backend/apps/catalog/api/__init__.py`.

```python
routers = [
    ("/models/", models_router),
    ("/titles/", titles_router),
    ("/manufacturers/", manufacturers_router),
    ("/people/", people_router),
]
```

Define explicit Ninja `Schema` classes for all request/response payloads (not `ModelSchema` — we want control over what's exposed). Key schemas: `PinballModelListSchema` (slim, for list view), `PinballModelDetailSchema` (full, with credits + provenance + extra_data), `ManufacturerSchema`, `PersonSchema`, `ClaimSchema`.

### Endpoints

**`GET /api/models/`** — Paginated list with filters:

- `?search=` — searches name, manufacturer name, and theme via `Q(name__icontains=...) | Q(manufacturer__name__icontains=...) | Q(theme__icontains=...)`. For extra_data: use `Cast(extra_data, TextField())` + `icontains` (works on both SQLite and PostgreSQL). Defined as explicit Ninja `FilterSchema` or manual Q-building, not admin-style search.
- `?manufacturer=` — manufacturer slug
- `?type=SS` — machine_type
- `?display=DMD` — display_type
- `?year_min=` / `?year_max=` — year range
- `?person=` — filter by person slug (via DesignCredit)
- `?ordering=` — name, -name, year, -year, -ipdb_rating, -pinside_rating
- `?page=` / `?page_size=` — pagination (default 25)

**`GET /api/models/{slug}/`** — Full detail including credits, extra_data, and provenance (active claims grouped by field with source + citation).

**`GET /api/manufacturers/`** — List with model counts.

**`GET /api/manufacturers/{slug}/`** — Detail with model list.

**`GET /api/people/`** — List with credit counts.

**`GET /api/people/{slug}/`** — Person detail with bio + all credited models grouped by role.

**`GET /api/sources/`** — List of all sources.
