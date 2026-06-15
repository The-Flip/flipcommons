# Working With Catalog Data

This is the index doc for working with the pinball catalog data: where it comes from, how it gets into the database, how to correct it, and where to explore it.

## Four repos

The catalog data ecosystem spans four sibling repos. This project (flipcommons) serves the data; the others source, patch, and analyze it.

- **flipcommons** (this repo) — serves the catalog. Pulls pindata's published seed JSON, ingests it as the baseline, replays the numbered data patches published by flippatch on top, exposes the API and frontend.
- **[pindata](https://github.com/deanmoses/pindata)** — the canonical **seed catalog**: the bulk of the catalog, for bootstrapping a new database. One Markdown file per entity (YAML frontmatter + prose), validated against JSON schemas, exported to JSON and published to Cloudflare R2. Seed only — data patches used to live here too, but now live in flippatch.
- **[flippatch](https://github.com/deanmoses/flippatch)** — the **data patches**: numbered `NNNN-slug.yaml` corrections applied incrementally on top of a seeded database. Authored and validated there, published to Cloudflare R2. See [DataPatches.md](DataPatches.md).
- **[pinexplore](https://github.com/deanmoses/pinexplore)** — read-only analysis. Builds a DuckDB database from pindata records plus external dumps (Wikidata, IPDB, OPDB etc) and runs integrity checks, cross-source comparisons and gap analysis. Not part of the serving path.

pindata and flippatch are upstream; flipcommons and pinexplore are independent consumers.

### Local layout convention

By convention, these repos live side by side under one parent directory on localhost dev, so `../pindata`, `../flippatch` and `../pinexplore` resolve from this repo. Tooling and docs assume that layout when they reference a sister project by relative path.

## How data reaches the database

Two stages, both manual — there is no auto-ingest on deploy or startup.

1. **Seed — the immutable baseline.** `ingest_all` loads pindata's exported JSON plus external sources (IPDB, OPDB) into a fresh database. The seed is **never edited to fix data**, and it is **only used to bootstrap a fresh database** — your local dev DB. Production is seeded **once** and never re-ingested. See [Ingest.md](Ingest.md).
2. **Patches — append-only corrections.** Every fix or ongoing source update is a small, numbered, replayable [data patch](DataPatches.md) applied on top of the seed. A fresh database reaches production's state by replaying seed → `0001` → `0002` → …. This is the everyday path once a database is seeded. See [DataPatches.md](DataPatches.md).

```bash
make pull-ingest      # fetch pindata's seed JSON + external sources from R2
make pull-patches     # fetch flippatch's data patches from R2
make ingest-all       # fresh dev DB only: seed, then replay all patches
make ingest-patches   # everyday path: apply pending patches to an already-seeded DB
```

## I want to…

- **Explore, validate or compare the data** → use [pinexplore](https://github.com/deanmoses/pinexplore) (DuckDB, read-only).
- **Understand the catalog model** (titles, models, variants, manufacturers, taxonomy) → [DomainModel.md](DomainModel.md).
- **Correct or update a catalog value** → author a [data patch](DataPatches.md), attributed to the source the fact came from. Snapshot localhost first so you can iterate.
- **Bootstrap a fresh local database** → `make pull-ingest && make pull-patches && make ingest-all`.
- **Apply pending corrections** to a seeded DB → `make pull-patches && make ingest-patches`.
- **Understand how a field's value is resolved** and audited → [Provenance.md](Provenance.md) (claims and resolution).
