# Data Ingestion

This project is populated via Django management commands. The main pipeline
(`ingest_all`) seeds internal data then imports external sources. Optional
enrichment commands (Fandom, Wikidata) run separately.

## Data sources

Catalog data and external source files are maintained in the
[pindata](https://github.com/deanmoses/pindata) repo and published to
Cloudflare R2. This project pulls them locally before running the ingest pipeline:

```bash
make pull-ingest   # download R2 → local data/ingest_sources/
```

## Pipeline overview

`ingest_all` runs these steps in order:

| Step               | What it does                                                                                                                                 |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `ingest_pindata`   | Seeds curated catalog data (taxonomy, manufacturers, corporate entities, systems, people, series, titles, models) from exported pindata JSON |
| `ingest_ipdb`      | Imports IPDB machine data                                                                                                                    |
| `ingest_opdb`      | Imports OPDB machines, groups, and changelog                                                                                                 |
| `resolve_claims`   | Re-resolves all catalog entities from claims                                                                                                 |
| `validate_catalog` | Validates the resolved catalog                                                                                                               |

## Vocabulary entities

Two vocabulary entities drive feature and reward classification across all ingest sources:

| Entity            | Source file             | Count | Notes                                              |
| ----------------- | ----------------------- | ----- | -------------------------------------------------- |
| `GameplayFeature` | `gameplay_feature.json` | ~159  | DAG hierarchy via `is_type_of`; aliases for lookup |
| `RewardType`      | `reward_type.json`      | 6     | Flat; aliases for lookup                           |

Both are ingested by `ingest_pindata` and populated before any external source ingest runs. All external sources (IPDB, OPDB) only _assign_ existing features/types to models — they never create new `GameplayFeature` or `RewardType` records.

### Shared vocabulary maps

`backend/apps/catalog/ingestion/vocabulary.py` provides DB-driven lookup maps used by both IPDB and OPDB ingest:

- `build_feature_slug_map()` — `{lowercase_term: slug}` from `GameplayFeature` names + aliases
- `build_reward_type_map()` — `{lowercase_term: slug}` from `RewardType` names + aliases
- `build_tag_map()` — `{lowercase_term: slug}` from `Tag` names + aliases
- `build_cabinet_map()` — `{lowercase_term: slug}` from `Cabinet` names + aliases

### IPDB feature extraction

IPDB's `NotableFeatures` field uses two separate extraction passes:

1. **Gameplay features** — Structured 4-step pipeline:
   - Clean: strip prefix, replace mojibake, insert comma before period+uppercase
   - Split: on comma or period+whitespace
   - Validate (ingest-blocking `CommandError`): quoted segments, segments containing "feature", segments > 60 chars
   - Parse: regex `^(.+?)\s*\(\d+.*\)$` extracts feature name from count-bearing segments; narrative patterns (`kickback`, `magna-save`, etc.) match remaining text
2. **Reward types** — Word-boundary keyword matching against raw text: `re.search(r'\b{term}\b', raw, re.IGNORECASE)` for each term in the reward type vocabulary.

Unmatched terms (those matching no vocabulary entry) are collected and printed as a warning: first 25 comma-separated, followed by the total count.

### OPDB feature classification

OPDB's `features` array uses a unified single-pass classification with priority ordering:

1. Reward type vocabulary (highest priority)
2. Gameplay feature vocabulary
3. Tag vocabulary
4. Cabinet vocabulary
5. "Conversion kit" and "Converted game" terms are silently skipped (conversion status is determined by the `converted_from` FK)

Terms in `_KNOWN_OPDB_VARIANT_LABELS` (LE, SE, Premium, Pro, etc.) are silently skipped. Any other unmatched term appears in the unmatched-term warning.

### Validation (ingest-blocking)

These conditions raise `CommandError` and abort ingest:

- A `model.json` entry references a nonexistent gameplay feature slug
- A `model.json` entry references a nonexistent reward type slug
- A `gameplay_feature.json` entry's `is_type_of` field references a nonexistent parent slug
- A `reward_type.json` or `gameplay_feature.json` description contains a wikilink (`[[<entity-type>:<public-id>]]`) referencing a nonexistent entity
- An IPDB `NotableFeatures` segment is quoted, contains "feature", or is > 60 characters

## External data sources

| Source           | File                        | Used by          |
| ---------------- | --------------------------- | ---------------- |
| IPDB             | `ipdbdatabase.json`         | `ingest_ipdb`    |
| OPDB machines    | `opdb_export_machines.json` | `ingest_opdb`    |
| OPDB groups      | `opdb_export_groups.json`   | `ingest_opdb`    |
| OPDB changelog   | `opdb_changelog.json`       | `ingest_opdb`    |
| Museum sign copy | `machine_sign_copy.csv`     | `ingest_pindata` |

## Optional enrichment commands

These are **not** part of `ingest_all` and are run separately after the main
pipeline:

| Command                         | Source      | What it does                                   |
| ------------------------------- | ----------- | ---------------------------------------------- |
| `ingest_fandom`                 | Fandom wiki | Imports design credits, persons, manufacturers |
| `ingest_wikidata`               | Wikidata    | Enriches Person records via SPARQL             |
| `ingest_wikidata_manufacturers` | Wikidata    | Enriches Manufacturer records via SPARQL       |

All three support `--dump` / `--from-dump` flags to cache raw data locally and
replay without network calls.

**Fandom data files** (stored in R2 with the other ingest sources):

- `fandom_games.json`
- `fandom_persons.json`
- `fandom_manufacturers.json`

## Running locally

```bash
make pull-ingest   # download data from R2
make ingest-all    # fresh-DB bootstrap: full seed pipeline, then data patches
```

Or as a single command (fresh-DB bootstrap: seed pipeline + data patches):

```bash
cd backend
uv run python manage.py pull_and_ingest --dest ../data/ingest_sources
```

## Running against production (Railway)

### Prerequisites

- Railway CLI installed and logged in (`railway login`)
- Project linked (`railway link`)

### 1. Pull data and run ingest (fresh / reset DB only)

```bash
railway ssh --service flip-commons
.venv/bin/python manage.py pull_and_ingest
```

This pulls ingest sources from R2 (with SHA-256 verification, skipping
unchanged files), runs the full `ingest_all` seed pipeline, then replays the
data-patch log so the DB matches production. Add `--dry-run` to verify the seed
without committing (patches are skipped in dry-run — they need a committed seed).

> **Only on a fresh or just-reset database.** An already-seeded production DB is
> never re-ingested: re-running the seed re-asserts the original source claims
> and clobbers same-source patch corrections, and the patch ledger then skips
> re-applying them. To apply new corrections to a live DB, use the patch path
> below.

### Applying data patches to a live (already-seeded) database

This is the everyday correction path once production is seeded — pull the latest
patch files, then apply only the pending ones (the ledger skips the rest):

```bash
railway ssh --service flip-commons
.venv/bin/python manage.py pull_ingest_sources --dest /tmp/ingest_sources
.venv/bin/python manage.py ingest_patches --patches-dir /tmp/ingest_sources/pindata/patches
```

Add `--dry-run` to `ingest_patches` to preview the claims without writing. See
[DataPatches.md](DataPatches.md) for the patch model.

### 2. Run optional enrichment (if needed)

```bash
.venv/bin/python manage.py ingest_fandom \
  --from-dump /tmp/ingest_sources/fandom_games.json \
  --from-dump-persons /tmp/ingest_sources/fandom_persons.json \
  --from-dump-manufacturers /tmp/ingest_sources/fandom_manufacturers.json

.venv/bin/python manage.py ingest_wikidata
.venv/bin/python manage.py ingest_wikidata_manufacturers
```

## Resetting the production database

Required when migrations have been collapsed (e.g. all apps reset to `0001`).

### 1. Wipe the database

In the Railway dashboard, open the **Postgres** service and use the query
runner, or connect via `railway connect Postgres` (requires `psql` locally):

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public;
```

Alternatively, delete and recreate the Postgres service in the Railway
dashboard (you will need to re-link `DATABASE_URL` to the app service).

### 2. Merge and deploy

Merge the branch into `main`. Railway auto-deploys and the `preDeployCommand`
runs `manage.py migrate`, rebuilding the schema from scratch.

### 3. Re-create your admin account

After the wipe, your admin row is gone. The admin password form is disabled, so `createsuperuser` produces a row that can never sign in. Instead, open the deployed site and sign up through WorkOS — even if your WorkOS identity still exists, Django sees no matching row and routes you through `/signup` to pick a handle, which creates a fresh `User`. Then grant admin access using the public `DATABASE_URL` from the Postgres service variables in the Railway dashboard:

```bash
cd backend
DATABASE_URL=<public-url> \
uv run python manage.py grant_admin you@example.com
```

### 4. Re-run ingest

Follow the [Running against production](#running-against-production-railway)
steps above.
