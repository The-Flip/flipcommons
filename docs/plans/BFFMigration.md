# BFF Migration Playbook

> Status: Not pursuing. This migration is obsolete because the proposed `pages/` split adds churn without enough architectural payoff.

How to migrate an existing catalog or provenance API module from the current flat structure into the `pages/` namespace.

For the target state (code structure, import rules, composition patterns), see [ApiDesign.md](../ApiDesign.md). For the architectural rationale behind the split, see [BFF.md](BFF.md).

## Before you start

Read the entity's current API module end to end. Understand which functions exist and what each does before deciding what moves.

## What moves and what stays

Each entity API module (e.g. `catalog/api/titles.py`) currently contains two kinds of code mixed together:

**Page composition** — moves to `pages/`:

- Queryset builders for detail pages (`_detail_qs`, `_model_detail_qs`, etc.)
- Page serializers (`_serialize_title_detail`, `_serialize_manufacturer_detail`, etc.)
- Helper functions used only by those serializers (`_compute_agreed_specs`, `_build_location_refs`, etc.)
- Page-specific schemas (`TitleDetailSchema`, `ManufacturerDetailSchema`, etc.)

**Resource API** — stays in `api/`:

- List endpoints (`list_titles`, `list_all_titles`, etc.)
- Claims editing endpoints (`patch_title_claims`, etc.)
- Router definitions and route decorators
- Resource-oriented schemas

**How to tell them apart:** If it's imported by `page_endpoints.py`, it's page composition. If it serves its own route or is used by claims editing, it's resource API.

## Triaging helpers.py

`catalog/api/helpers.py` contains shared utilities. Audit each helper during migration — see [ApiDesign.md § Shared page helpers](../ApiDesign.md#shared-page-helpers) for the decision rule.

Current assessment:

**Stay in `api/helpers.py`** (used by both page and resource API):

- `_extract_image_urls`, `_uploaded_image_urls`, `_media_prefetch` — used by page detail serializers AND `list_all_*` bulk endpoints
- `_serialize_credit`, `_intersect_facet_sets`, `_serialize_title_ref`, `_serialize_title_machine` — generic utilities

**Move to `pages/helpers.py`** (only used by page composition):

- `_build_rich_text`, `_extract_description_attribution` — build attributed rich text for detail pages only

Re-audit as each entity is migrated. A helper that looks shared might turn out to be page-only once all its callers have moved.

## Step-by-step for one entity

### 1. Identify the functions to move

Read the entity's API module. List every function and schema, and categorize each as page composition or resource API. Write this down before moving anything.

### 2. Create the pages module

Create `catalog/pages/__init__.py` and `catalog/pages/{entity}.py`. If `catalog/pages/` already exists from a prior migration, just add the new entity file.

### 3. Move page-composition functions

Move the identified functions and their page-specific schemas into `pages/{entity}.py`. Update imports:

- Cross-app imports (`build_sources`, `claims_prefetch`, etc.) come with the functions.
- Same-app imports from `api/helpers.py` become `from apps.catalog.api.helpers import ...`.
- Same-app model imports stay as-is.

### 4. Improve as you move

As you move page composition code, refactor it to match the patterns in [ApiDesign.md § Writing page composition code](../ApiDesign.md#writing-page-composition-code):

- Decompose monolithic serializers into focused builder functions
- Name builders for what they produce, not with `_serialize_` prefixes
- Extract shared patterns into `pages/helpers.py`

Don't refactor and move in the same commit — move first, then improve. This keeps diffs reviewable.

### 5. Update page_endpoints.py

Change `page_endpoints.py` to import from `pages/{entity}` instead of from `api/{entity}`. Names will change after the refactor step — update these imports to match.

### 6. Clean up the resource API module

After moving page functions out, verify the resource API module no longer imports from peer apps for page composition:

- `build_sources` / `claims_prefetch` imports are gone (unless legitimately used — `edit_claims` imports are fine)
- `EntityMedia` imports are gone (unless resource list endpoints use them directly)

### 7. Run tests

```bash
make test
```

Page endpoints are exercised by existing integration tests — if imports are wired correctly, tests should pass without modification.

## Provenance is different

Provenance's `page_endpoints.py` is structured differently from catalog's:

- It's a flat module with more inline logic
- It uses `resolve_entity_type()` and `build_entity_links()` for entity-agnostic routing
- It defines schemas inline rather than importing them

The same principle applies — extract composition logic into `provenance/pages/` — but the functions to extract are different. Read the module and apply the same categorization criteria.

## Migration order

One entity at a time. Suggested order within catalog:

1. **Titles** — largest, most representative, good test of the pattern
2. **Machine models** — most complex (variants, conversions, remakes)
3. **Manufacturers** — corporate hierarchy traversal
4. **Remaining entities** (series, people, franchises, gameplay_features, themes, systems, corporate_entities, taxonomy) — smaller, same pattern

Provenance can be migrated independently after catalog.

## Verification checklist

After each entity migration:

- [ ] `page_endpoints.py` imports from `pages/`, not from `api/{entity}`
- [ ] Resource API module has no page-composition cross-app imports remaining
- [ ] `pages/` module does not contain any write operations or business invariants
- [ ] `make test` passes
- [ ] `make lint` passes
