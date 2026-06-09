# Working With Catalog Data

This is the index doc for working with the pinball catalog data: where it comes from, how it gets into the database, how to correct it, and where to explore it.

## Three repos

The catalog data ecosystem spans three sibling repos. This project (flipcommons) serves the data; the other two source and analyze it.

- **flipcommons** (this repo) — serves the catalog. Pulls pindata's published JSON, ingests it as the seed baseline, replays numbered data patches on top, exposes the API and frontend.
- **[pindata](https://github.com/deanmoses/pindata)** — the canonical data source. It contains two types of data:
  - _seed data_: the bulk of the catalog, for bootstrapping a new database. One Markdown file per entity (YAML frontmatter + prose), validated against JSON schemas, exported to JSON and published to Cloudflare R2.
  - _patch data_: numbered **data patches** in YAML format, to apply incremental updates to a running database. See [DataPatches.md](DataPatches.md).
- **[pinexplore](https://github.com/deanmoses/pinexplore)** — read-only analysis. Builds a DuckDB database from pindata records plus external dumps (Wikidata, IPDB, OPDB etc) and runs integrity checks, cross-source comparisons and gap analysis. Not part of the serving path.

pindata is upstream of both; flipcommons and pinexplore are independent consumers of it.

### Local layout convention

By convention, these repos live side by side under one parent directory on localhost dev, so `../pindata` and `../pinexplore` resolve from this repo. Tooling and docs assume that layout when they reference a sister project by relative path.

## How data reaches the database

Two stages, both manual — there is no auto-ingest on deploy or startup.

1. **Seed — the immutable baseline.** `ingest_all` loads pindata's exported JSON plus external sources (IPDB, OPDB) into a fresh database. The seed is **never edited to fix data**, and it is **only used to bootstrap a fresh database** — your local dev DB. Production is seeded **once** and never re-ingested. See [Ingest.md](Ingest.md).
2. **Patches — append-only corrections.** Every fix or ongoing source update is a small, numbered, replayable [data patch](DataPatches.md) applied on top of the seed. A fresh database reaches production's state by replaying seed → `0001` → `0002` → …. This is the everyday path once a database is seeded. See [DataPatches.md](DataPatches.md).

```bash
make pull-ingest      # fetch pindata's JSON + patches from R2 → data/ingest_sources/
make ingest-all       # fresh dev DB only: seed, then replay all patches
make ingest-patches   # everyday path: apply pending patches to an already-seeded DB
```

## I want to…

- **Explore, validate or compare the data** → use [pinexplore](https://github.com/deanmoses/pinexplore) (DuckDB, read-only).
- **Understand the catalog model** (titles, models, variants, manufacturers, taxonomy) → [DomainModel.md](DomainModel.md).
- **Correct or update a catalog value** → author a [data patch](DataPatches.md), attributed to the source the fact came from. Snapshot localhost first so you can iterate.
- **Bootstrap a fresh local database** → `make pull-ingest && make ingest-all`.
- **Apply pending corrections** to a seeded DB → `make pull-ingest && make ingest-patches`.
- **Understand how a field's value is resolved** and audited → [Provenance.md](Provenance.md) (claims and resolution).
