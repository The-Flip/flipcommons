# All The Data: Canonical this project Records Without Losing Provenance

## Goal

Scale Pindata content to cover the full catalog of all pinball machines in existence while preserving the following:

- Pindata canonical facts and relationships
- Independent source attribution for OPDB/IPDB-derived facts
- Git-friendly review and rollback
- AI-friendly record editing without giant monolithic files

Target scope:

- Every title and model in the catalog
- Rich descriptions for every record of every entity: model, title, person, manufacturer, system, theme, technology generation, etc
- Full manufacturer and corporate-entity history
- Broad coverage of people, aliases, and bios

## Summary

This project should stop growing the large aggregate files like `data/models.json` and `data/titles.json` as the main authoring surface.

Instead, this project should move to a three-layer architecture:

1. `data/ingest_sources/` remains immutable third-party evidence.
2. `data/pindata/` becomes the Flipcommons-authored canonical layer, stored as one Markdown file per entity with YAML frontmatter.
3. The Django SQLite database remains the operational source of truth after ingestion and claim resolution.

This keeps the provenance model, but changes the authority boundaries:

- Pindata files become canonical for the runtime graph and for all relationship-shaping data.
- OPDB and IPDB remain ingested as claims only for non-relational factual fields.
- OPDB/IPDB relationships are preserved for comparison and research, not for driving runtime resolution.

## Why Change

The current JSON files worked well as a small editorial overlay, but they are no longer the right shape for a catalog-scale knowledge base.

Problems with the current flat-file approach:

- Large aggregate files are hard to review, diff, and safely edit.
- AIs make ID, slug, and cross-reference mistakes when too many records live in one file.
- Narrative descriptions are awkward inside JSON string literals.
- The current files blur "Flipcommons-authored canon" and "facts imported from external datasets."
- The current runtime ingest gives too much power to OPDB relationship structures like groups and aliases.
- The OPDB ingest path has become too complex because it is trying to translate a third-party editorial model into this project's own graph.

Problems with making one big per-title JSON blob:

- Models are first-class entities in the Django catalog and claims system.
- Model-specific prose, variants, remakes, and conversions deserve their own files.
- Editing one model should not rewrite an entire title bundle.

## Proposed Data Model

### Principle: one file per entity

Pindata entities each get their own file:

```text
data/
  ingest_sources/                 # immutable third-party inputs
  pindata/
    titles/
      medieval-madness.md
      attack-from-mars.md
    models/
      medieval-madness.md
      medieval-madness-remake.md
    people/
      brian-eddy.md
      steve-ritchie.md
    manufacturers/
      williams.md
      bally.md
    corporate_entities/
      williams-manufacturing-company.md
      williams-electronics.md
    cabinets/
      standard.md
      mini.md
    credit_roles/
      design.md
      art.md
    display_types/
      dot-matrix.md
      lcd.md
    display_subtypes/
      sega-192x64.md
    franchises/
      star-wars.md
    game_formats/
      pinball-machine.md
    gameplay_features/
      multiball.md
    series/
      williams-wpc-95.md
    systems/
      wpc-95.md
    tags/
      castle.md
    themes/
      fantasy.md
    technology_generations/
      solid-state.md
    technology_subgenerations/
      dot-matrix-era.md
```

The format rule should be simple:

- `data/pindata/` contains authored Markdown records only
- `data/ingest_sources/` contains raw third-party dumps in their original formats
- generated exports for explore/validation may use JSON, but they are build artifacts, not authored canon

### Why Markdown with frontmatter

Markdown-with-frontmatter is a better fit than pure JSON for authored catalog records:

- Frontmatter handles IDs, slugs, dates, booleans, and relationships cleanly.
- The body is ideal for prose descriptions, markdown links, and editorial notes.
- Git diffs stay readable.
- AIs usually edit a single Markdown file more safely than a large JSON array.
- One consistent authored format keeps the repo easier to understand and tool.

### Example title record

```md
---
slug: medieval-madness
name: Medieval Madness
opdb_group_id: GrB14
franchise_slug: medieval-madness
series_slug: williams-wpc-95
abbreviations:
  - MM
model_slugs:
  - medieval-madness
  - medieval-madness-remake
---

Medieval Madness is a fantasy-themed title centered on castle destruction,
taunting rulers, and a highly theatrical presentation.
```

### Example model record

```md
---
slug: medieval-madness
name: Medieval Madness
title_slug: medieval-madness
opdb_id: GrB14-M0Ry6
ipdb_id: 4032
manufacturer_slug: williams
year: 1997
month: 6
player_count: 4
flipper_count: 2
display_type_slug: dot-matrix
technology_generation_slug: solid-state
technology_subgeneration_slug: dot-matrix-era
system_slug: wpc-95
cabinet_slug: standard
game_format_slug: pinball-machine
tag_slugs:
  - castle
  - fantasy
credit_refs:
  - person_slug: brian-eddy
    role: Design
  - person_slug: greg-freres
    role: Art
---

This model is widely regarded as one of the defining Williams games of the
late WPC era, combining fast flow with a densely integrated ruleset.
```

Optional fields are simply omitted when null, empty, or false. Only fields with meaningful values appear in frontmatter.

### Example person record

```md
---
slug: brian-eddy
name: Brian Eddy
---

Brian Eddy is a designer and programmer associated with several highly
regarded 1990s Williams titles.
```

### Example manufacturer record

```md
---
slug: williams
name: Williams
---

Williams was one of the central American pinball manufacturers of the solid
state era and the parent manufacturer behind many canonical tables.
```

### Example corporate entity record

Corporate entities are standalone files in `data/pindata/corporate_entities/`, each pointing at its parent manufacturer via `manufacturer_slug`:

```md
---
slug: williams-manufacturing-company
name: Williams Manufacturing Company
manufacturer_slug: williams
year_start: 1943
year_end: 1964
headquarters_city: Chicago
headquarters_state: Illinois
headquarters_country: USA
---
```

### Example taxonomy record

```md
---
slug: solid-state
name: Solid State
display_order: 20
---

Solid-state games use transistorized electronics rather than electromechanical
score reels and relay-driven control logic.
```

## Source-of-Truth Rules

This part matters most.

### Third-party data is evidence, not canon

Files in `data/ingest_sources/` remain raw snapshots from OPDB, IPDB, Fandom, and other external sources. They are not edited by hand.

### This project files are the authored canonical layer

Files in `data/pindata/` express Flipcommons-authored choices:

- canonical facts this project wants the app to resolve to
- editorial descriptions
- This project slugs
- link-rich markdown prose
- aliases
- franchise and series relationships
- corrections to third-party data
- additional facts this project wishes to assert directly
- all relationship-shaping judgments such as title membership, variants, remakes, conversions, and graph structure

Every authored record in `data/pindata/` should use the same Markdown-with-frontmatter format, including smaller taxonomy entities. There should not be a split between "serious records in Markdown" and "small records in JSON."

### SQLite remains the runtime truth

The live Django catalog in SQLite remains the actual resolved state of the app after claims ingestion.

That means:

- This project files are not replacing the claims system.
- This project files are the highest-authority authored input to the claims system.
- OPDB still ingests as its own `Source`, narrowed to non-relational scalar claims only.
- IPDB still ingests as its own `Source` for scalar claims plus relationship claims (themes, gameplay features, credits) that provide bulk coverage at lower priority.

## Non-Negotiable Provenance Rule

Do not retire `ingest_opdb` or `ingest_ipdb` entirely.

They should continue to assert claims from external sources, because that is how this project preserves:

- attribution
- verification
- source comparison
- future refreshes when upstream data changes

But those ingests should be narrowed aggressively.

This project should absorb OPDB/IPDB facts into its own authored files for canonical runtime use. At the same time, this project should keep OPDB/IPDB claims as a comparison layer for straightforward facts.

### External claims: what stays, what goes

Now that this project Markdown records carry `opdb_id` and `ipdb_id`, matching external records to this project entities is reliable. This changes the cost/benefit calculus for some relationship claims that the original plan proposed stripping.

#### OPDB claim allowlist

OPDB continues to assert claims for non-relational scalar fields only:

- `name`
- `manufacturer`
- `year`
- `month`
- `player_count`
- `technology_generation`
- `display_type`
- `cabinet`
- `production_quantity`
- `flipper_count`
- `opdb_id`
- `abbreviation` (on titles, from shortname — additive, non-conflicting)

OPDB stops asserting:

- `title` (model→title linkage) — this project owns title grouping via Markdown files with `opdb_group_id`
- `variant_of` — this project owns variant relationships via Markdown model files
- Title creation from groups — this project owns all Title records
- All non-physical group promotion, alias classification, and chain-collapse heuristics

This is the biggest simplification: the alias-driven relationship inference in `ingest_opdb.py` can be removed entirely.

#### IPDB claim allowlist

IPDB continues to assert claims for non-relational scalar fields, **plus** several relationship types that provide high-value coverage this project cannot easily replicate:

Non-relational (unchanged):

- `name`
- `manufacturer`
- `year`
- `month`
- `player_count`
- `production_quantity`
- `ipdb_rating`
- `ipdb_id`
- `technology_generation`
- `system`
- `abbreviation`

Relationship claims **kept from IPDB**:

- `theme` — IPDB is the only bulk source of theme data. This project can override individual machines at priority 300.
- `gameplay_feature` — same rationale as themes; decent parsing, useful coverage.
- `credit` (+ Person creation) — IPDB provides thousands of credit rows across 585+ people. This project Markdown has credits for ~389 models from Phase 2; IPDB fills the remaining coverage. This project `credit_refs` assert at priority 300 and win when present.

IPDB also continues to create CorporateEntity and Address records (founding years, locations) — useful data that's hard to replicate manually.

#### This project ingest must wire up relationship claims

For the priority-300 override to work, this project model ingest needs to assert claims for fields it currently only stores in frontmatter:

- `credit_refs` → credit relationship claims
- `tag_slugs` → tag relationship claims
- Model-level themes (if/when added to the Markdown schema)

#### Explicitly not ingested from any external source

- source-specific prose and note fields (stored as extra data, not claims)
- source-specific keyword or feature buckets that don't map cleanly to this project taxonomy

### Images remain a separate attributed ingest path

Images are not "facts" in the same sense as year, manufacturer, or player count. They should remain externally sourced media with attribution and source metadata.

That means:

- OPDB/IPDB image ingest should survive
- image provenance should remain explicit
- image ingest should not participate in relationship resolution
- image ingest can be simplified independently of fact/relationship ingest

### OPDB must stop shaping the runtime graph

Do not let OPDB ingest define or infer:

- title grouping
- alias-driven `variant_of`
- clone relationships
- conversion relationships
- remake relationships
- canonical title membership
- franchise/series relationships

In practice, this means the biggest simplification target is OPDB groups/aliases and the relationship inference built around them. The non-physical group promotion, alias classification, and chain-collapse logic can all be removed.

Raw OPDB relationship data (groups, aliases) should live only in compare-oriented DuckDB tables and related exploration artifacts. It should not be ingested into runtime catalog claims.

### IPDB relationship claims are welcome at lower priority

IPDB relationship claims (themes, gameplay features, credits) are valuable bulk data that this project cannot easily replicate. They are ingested at IPDB's source priority and this project editorial claims override them at priority 300 when present.

The key distinction: IPDB relationship claims are additive enrichment data with clean parsing and straightforward semantics. OPDB relationship claims are editorial structure (groups, aliases, variant classification) that conflicts with this project's own graph design.

### This project owns the graph shape

Regardless of which external claims survive, this project is the authority for:

- title grouping (which models belong to which title)
- variant/remake/conversion relationships
- franchise and series membership
- tags
- any editorial corrections to IPDB themes, features, or credits

## DuckDB's Role

DuckDB is valuable, but it should remain an exploration, reconciliation, and audit tool.

Use DuckDB for:

- looking up correct OPDB/IPDB IDs before editing
- finding missing coverage
- checking relationships across sources
- generating migration candidates
- validating completeness and integrity

Do use DuckDB merged views as a practical bootstrap input for the migration.

Do not use DuckDB merged views as the sole or normative source for the migration.

Why not:

- `merged_titles` and `merged_models` are already resolved projections
- they intentionally collapse distinctions between this project, OPDB, and IPDB
- seeding canon from them naively risks freezing a lossy merged interpretation

Better migration seed inputs:

- DuckDB merged views, used as bootstrap candidate output
- current this project flat files
- raw OPDB/IPDB/Fandom dumps
- the runtime SQLite database and its claims tables

Recommended stance:

- use `merged_titles` and `merged_models` to generate first-pass skeleton files quickly
- treat that output as candidate canon to be normalized and corrected
- prefer explicit this project rules over merged-view output whenever relationship-shaping fields are involved

## File Semantics

### Titles

Title files should contain title-level data only:

- slug
- name
- OPDB/IPDB cross-reference IDs where useful
- franchise/series linkage
- abbreviations
- `split_from_opdb_group` when this project intentionally breaks a title away from an OPDB grouping decision
- title-level description
- explicit list of model slugs

They should not inline all model records.

### Models

Model files should contain model-level data only:

- slug
- name
- title linkage
- OPDB/IPDB IDs
- manufacturer/year/month/player count/flipper count/production quantity
- variant/remake/conversion relationships
- technology generation and subgeneration
- display type and subtype
- system
- cabinet
- game format
- tags
- model-level credits
- model-level description

All slug reference fields should use the `_slug` suffix consistently (e.g. `display_type_slug`, `cabinet_slug`, `technology_generation_slug`).

These relationship fields are canonical this project assertions, not imported behavior from OPDB aliases or groups.

### People

Person files should contain:

- slug
- name
- aliases
- birth/death data when available
- hometown/address or geography when available
- biography body

### Manufacturers

Manufacturer files should contain:

- slug
- name
- aliases
- manufacturer description body

Manufacturer files do not contain corporate entities. Corporate entities are standalone files that point back at their manufacturer via `manufacturer_slug`.

### Corporate entities

Corporate entity files should contain:

- slug (generated from slugified name)
- name
- manufacturer_slug (FK to manufacturer)
- year_start / year_end
- headquarters city/state/country when available
- description body (for future editorial prose)

### Taxonomy entities

Taxonomy entities should also be individual Markdown records:

- cabinets
- credit roles
- display types
- display subtypes
- franchises
- game formats
- gameplay features
- series
- systems
- tags
- themes
- technology generations
- technology subgenerations

Some of these records may have only frontmatter at first. That is fine. The benefit is consistency: every authored this project record has the same editing and validation model.

Some taxonomy entities are hierarchical. The schema should support relationship fields such as `parent_slug` where appropriate, for example:

- display subtypes belonging to display types
- technology subgenerations belonging to technology generations
- any future taxonomy tree this project chooses to model explicitly

### Golden records

Golden records are validation assertions, not entity records. They do not fit the one-file-per-entity Markdown pattern because their purpose is spot-check verification across multiple entity types and fields.

Golden records should remain as JSON in `data/golden_records.json`. They are consumed by DuckDB contract checks in `04_checks.sql` and are not inputs to the claims system. Moving them to Markdown would add complexity without benefit.

## Credits Strategy

Credits should be embedded in the authored records they belong to.

That means:

- model-level credits live in model files as `credit_refs`
- series-level credits live in series files as `credit_refs`

This matches the current data shape well because most models and series have only a handful of credits, and each credit is currently just a role plus a person slug.

If credits later grow richer metadata or standalone prose, the format can be refactored then. For now, embedding keeps the authored layer simpler.

Note: the current standalone `data/credits.json` (series-level credits) will be merged into the corresponding series Markdown files during migration. There will be no separate credits file in the new layout.

## Migration Plan

### Critical dependency: OPDB simplification requires this project files first

The plan's end-state goal is to strip relationship-shaping claims from OPDB/IPDB ingest. But this cannot happen until pindata files supply those relationships, or the catalog will lose data.

The dependency chain is:

1. This project Markdown files must exist and contain relationship-shaping fields.
2. This project ingestion must read those files and assert relationship claims.
3. Only then can OPDB/IPDB ingest stop asserting relationship claims.

This means OPDB simplification is the _goal_ of this project, not a prerequisite. The migration phases below are sequenced to respect this dependency.

### Phase 0: Field ownership matrix ✓

Produced a field-by-field ownership matrix by querying the Django claims table. Stored in `docs/plans/field-ownership-matrix.md`.

Key findings:

- Relationship-shaping denylist: `title`, `variant_of`, `credit`, `theme`, `gameplay_feature`
- All taxonomy fields are already Pindata-only
- 14 non-relational fields remain in the OPDB/IPDB comparison allowlist

### Phase 1: Schemas and loader ✓

Created 14 JSON Schema files in `data/schemas/pindata/`:

- `title.schema.json`, `model.schema.json`, `person.schema.json`, `manufacturer.schema.json`
- `corporate_entity.schema.json`, `series.schema.json`, `system.schema.json`
- `franchise.schema.json`, `theme.schema.json`
- `taxonomy.schema.json` (shared by cabinets, credit_roles, display_types, game_formats, gameplay_features, tags)
- `display_subtype.schema.json`, `technology_generation.schema.json`, `technology_subgeneration.schema.json`

Built a shared loader at `backend/apps/catalog/ingestion/pindata_loader.py`:

- Parses Markdown + YAML frontmatter
- Validates against JSON schemas (using `jsonschema` library, added as dependency)
- Exposes entity iterators (`iter_titles`, `iter_models`, etc.) and JSON-compatible adapter functions (`load_titles_as_dicts`, etc.)
- Single read path for Django ingestion, validation, and generation

Built a validation script at `scripts/validate_pindata_records.py`:

- Schema validation, slug/filename match, slug uniqueness, OPDB ID uniqueness
- Cross-entity reference integrity (model→title, title→model, credit→person, etc.)
- Self-referential and chained variant_of detection

### Phase 2: Generate first batch ✓

Generated ~1,195 Markdown records from existing `data/*.json` files using `scripts/bootstrap_pindata_markdown.py`:

- 389 models, 371 titles, 128 franchises, 90 corporate entities, 73 systems, 59 manufacturers, 19 people, 5 series (with credits merged from credits.json), plus ~160 taxonomy records

Design decisions made during execution:

- Corporate entities are standalone files (not embedded in manufacturer files), each with a generated slug and `manufacturer_slug` FK
- Series-level credits from `data/credits.json` are merged into series files as `credit_refs`
- Optional fields with null values, empty lists, empty strings, or false booleans are omitted from frontmatter

### Phase 3: Generate full catalog ✓

Generated the remaining catalog records from the Django SQLite runtime database using `scripts/export_full_catalog.py`:

- 6,440 additional models, 5,853 titles, 715 manufacturers, 566 people, 597 themes
- Phase 2 files were preserved; Phase 3 only created files for records not already present
- Title `model_slugs` backfilled from model→title linkage

Final totals: 15,366 Markdown files across 18 directories in `data/pindata/`:

| Entity                    | Files |
| ------------------------- | ----- |
| models                    | 6,829 |
| titles                    | 6,224 |
| manufacturers             | 774   |
| themes                    | 597   |
| people                    | 585   |
| franchises                | 128   |
| corporate_entities        | 90    |
| systems                   | 73    |
| gameplay_features         | 20    |
| credit_roles              | 10    |
| display_types             | 6     |
| tags                      | 6     |
| display_subtypes          | 5     |
| series                    | 5     |
| cabinets                  | 4     |
| game_formats              | 4     |
| technology_generations    | 3     |
| technology_subgenerations | 3     |

3 pre-existing OPDB ID duplicates flagged (data quality issue in Django DB, not a migration bug).

### Phase 4: Update Django ingestion (dual-mode) ✓

All 8 this project ingestion commands now support `--format markdown` (default remains `json`):

- `ingest_pindata_taxonomy`, `ingest_pindata_manufacturers`, `ingest_pindata_corporate_entities`
- `ingest_pindata_systems`, `ingest_pindata_people`, `ingest_pindata_series`
- `ingest_pindata_titles`, `ingest_pindata_models`

`ingest_all` passes `--format` through to all this project commands.

JSON-compatible adapter functions in `pindata_loader.py` translate Markdown frontmatter field names to the JSON field names the existing ingest code expects (e.g. `title_slug` → `title`). The claims pipeline is unchanged.

Smoke-tested: taxonomy and systems produce zero new claims (identical data); the full catalog produces new claims for records that only existed in OPDB/IPDB before.

### Phase 5: DuckDB explore layer + verification

Before narrowing OPDB/IPDB ingest, add the new this project Markdown data to DuckDB so it can be explored side-by-side with existing OPDB/IPDB/merged views. This is the verification step that builds confidence before stripping external claims.

Steps:

1. Write a Python export script that reads `data/pindata/**/*.md` via the shared loader and emits normalized JSON files into `data/explore/pindata/`.
2. Add DuckDB views in `01_raw.sql` that read those exported JSON files as `pindata_md_models`, `pindata_md_titles`, etc. — alongside the existing `pindata_models`, `pindata_titles` views that read `data/*.json`.
3. Write comparison queries: join Markdown-layer data against merged views and OPDB/IPDB raw views to surface discrepancies in slugs, names, relationships, and field coverage.
4. Fix data quality issues discovered during exploration: slug naming (e.g. obscure games holding simple slugs, slugs that don't match full names), relationship correctness, missing fields.

This phase is iterative — export, explore, fix, re-export — until the Markdown layer is trustworthy.

### Phase 6: Narrow OPDB ingest, keep IPDB relationships

Only safe after Phase 5, when the Markdown layer has been verified via DuckDB comparison.

Changes to `ingest_opdb.py`:

- stop asserting claims for: `variant_of`, `converted_from`, `is_conversion`, `title`, `clone_of`, and any other relationship-shaping fields
- stop creating Title records from groups (this project owns all titles)
- stop running non-physical group heuristics and alias-driven relationship classification
- remove the three-way variant/clone/conversion classification, chain-collapse logic, and `models.json` override plumbing
- keep asserting claims for the OPDB scalar allowlist fields only
- keep image ingest unchanged
- keep OPDB group/alias data flowing into DuckDB exploration views for comparison

Changes to `ingest_ipdb.py`:

- **keep** theme, gameplay feature, and credit relationship claims (these provide bulk coverage this project can selectively override at priority 300)
- keep asserting claims for the IPDB scalar allowlist fields
- keep CorporateEntity and Address creation
- keep image ingest unchanged

Changes to this project model ingest (`ingest_pindata_models.py`):

- wire up `credit_refs` from Markdown frontmatter as priority-300 credit relationship claims
- wire up `tag_slugs` from Markdown frontmatter as priority-300 tag relationship claims
- this ensures this project editorial data wins over IPDB when both sources have data for the same model

The biggest simplification target remains OPDB: the non-physical group promotion, alias-driven relationship inference, and `models.json` override machinery can all be removed.

### Phase 7: Validation and checks

Extend the current validation approach with provenance-focused checks:

- if a this project record references an OPDB or IPDB ID, that ID should be discoverable in the raw dumps or runtime source tables
- if this project overrides a field already imported from OPDB/IPDB, the override is visible as a higher-priority editorial claim
- if OPDB still asserts any relationship-shaping claim field (title, variant_of, etc.), fail validation
- IPDB relationship claims (themes, gameplay features, credits) are expected and should not trigger validation failures
- if runtime relationships differ from OPDB/IPDB relationship data, expose that as an intentional divergence report rather than a catalog error

Basic structural checks (slug uniqueness, cross-references, chained variants, filename/slug match, OPDB ID uniqueness) are already implemented in `scripts/validate_pindata_records.py`.

### Phase 8: Cutover and cleanup

Do not delete the old authored JSON files immediately.

Staged cutover:

1. Switch default ingestion to Markdown (remove the dual-mode flag).
2. Run full ingest and compare catalog output against the last JSON-based ingest.
3. Fix any remaining discrepancies.
4. Retire the old authored JSON files only after parity is demonstrated.
5. Remove the legacy JSON reading code from ingestion commands.

This avoids a one-shot migration that quietly changes catalog behavior.

## AI Editing Workflow

When an AI needs to add or update a record, it should **query DuckDB first** to look up correct IDs and relationships, rather than guessing or searching through files:

```sql
-- Find the correct OPDB ID for a machine
SELECT opdb_id, name, manufacturer, year FROM opdb_machines
WHERE name ILIKE '%medieval%';

-- Find the OPDB group for a title
SELECT group_id, group_name FROM opdb_groups
WHERE group_name ILIKE '%batman%';

-- Check what models already exist for a title
SELECT * FROM merged_models WHERE group_id = 'GrB14';
```

The existing `data/explore/explore.duckdb` (rebuilt via `make explore`) already supports these queries.

The full workflow:

1. Query DuckDB to find correct IDs and existing relationships.
2. Edit only the relevant entity file in `data/pindata/`.
3. Run schema validation and integrity checks.
4. Ingest or dry-run ingest to confirm the resulting claims are sensible.

This sharply reduces the chance of:

- wrong OPDB IDs
- wrong slugs
- accidental duplicates
- orphaned relationships

## Suggested Commands and Tooling

Add small focused tools rather than one giant migration script.

Recommended commands:

- `make pindata-export`
  - build normalized JSON from Markdown for explore/validation
- `make pindata-validate`
  - validate frontmatter schemas and relationship integrity
- `make explore`
  - rebuild DuckDB from exported JSON + ingest_sources files
- `uv run python manage.py ingest_pindata_titles`
- `uv run python manage.py ingest_pindata_models`
- `uv run python manage.py ingest_opdb`
- `uv run python manage.py ingest_ipdb`

Possible helper scripts:

- `scripts/export_pindata_records.py`
- `scripts/validate_pindata_records.py`
- `scripts/bootstrap_pindata_markdown.py`

### Enrichment sources

The following ingestion commands are not affected by this migration and should continue to operate as they do today:

- `ingest_fandom.py` — Fandom wiki bios, manufacturer metadata
- `ingest_wikidata.py` — Wikidata person data
- `ingest_wikidata_manufacturers.py` — Wikidata manufacturer data

These are non-relational enrichment sources that assert claims through the normal provenance pipeline. Nothing in this plan changes their behavior.

Pinball Map data (`data/ingest_sources/pinballmap_*.json`) does not have a Django ingest command, but is already imported into DuckDB as `pinballmap_machines` and `pinballmap_machine_groups` views. That should continue unchanged — DuckDB is a valid enrichment path for exploration and reconciliation data that doesn't need to flow through the claims pipeline.

### `ingest_pindata_signs` is retired

The museum sign copy ingest (`ingest_pindata_signs.py`, source `flip-signs`, priority 50) should be retired after migration.

Its valuable content is the long-form educational text (MainText column), which should be absorbed into `data/pindata/titles/*.md` body text during Phase 2/3 generation. Once those descriptions live in pindata files, they become canonical at priority 300.

The other claims it asserts (name, year, month, manufacturer, production_quantity, credits) are redundant with higher-priority sources (OPDB at 200, IPDB at 100, this project at 300) and add no unique value.

After migration:

- absorb MainText descriptions into title Markdown files
- remove `ingest_pindata_signs` from `ingest_all` orchestration
- the raw CSV (`data/ingest_sources/machine_sign_copy.csv`) remains in ingest_sources as archival evidence

### `ingest_all` orchestration

`ingest_all` should survive, but its phase ordering needs to change to reflect the new architecture.

At a high level, the new orchestration should be:

1. ingest Pindata canonical records (from `data/pindata/`)
2. ingest OPDB/IPDB non-relational comparison claims
3. ingest enrichment sources (Fandom, Wikidata)
4. ingest externally sourced images with attribution
5. resolve claims
6. run validation and divergence checks

## Sizing Estimates

Actual file counts after Phase 3 generation:

| Entity               | Files |
| -------------------- | ----- |
| Models               | 6,829 |
| Titles               | 6,224 |
| Manufacturers        | 774   |
| Themes               | 597   |
| People               | 585   |
| Franchises           | 128   |
| Corporate Entities   | 90    |
| Systems              | 73    |
| Taxonomy (all types) | 78    |

Total: 15,366 files across 18 directories. Each individual file fits comfortably in an AI context window. Git handles this file count trivially.

## Open Questions

No open architectural questions. Format, provenance, credits, golden records, corporate entities, enrichment sources, and external-relationship decisions have all been made and implemented through Phase 4.

Remaining work is execution of Phases 5–8.

## Recommendation

Adopt the per-entity file strategy from the original plan, but refine it as follows:

- one file per title, model, person, and manufacturer
- Markdown with frontmatter for all Pindata entities
- make Pindata files canonical for runtime facts and relationships
- keep OPDB/IPDB ingestion as independent provenance-bearing sources for non-relational fact claims only
- remove OPDB groups/aliases from the main runtime graph-building path
- keep DuckDB as an audit/reconciliation tool
- migrate gradually with parity checks before retiring legacy files

This gets the AI ergonomics and Git reviewability benefits you want while also cutting out the most brittle source of ingest complexity: letting OPDB's relationship model shape this project's runtime graph.
