# Working With Catalog Data

This is the index doc for working with the pinball catalog data: where it comes from, how it gets into the database, how to correct it, and where to explore it.

## Sibling repos

The catalog data ecosystem spans several sibling repos. This project (flipcommons) serves the data; the others source, patch and analyze it.

- **flipcommons** (this repo) — serves the catalog. Applies the numbered data patches published by flippatch, exposes the API and frontend.
- **[flippatch](https://github.com/deanmoses/flippatch)** — the **data patches**: numbered `NNNN-slug.yaml` files, the sole bulk write path into the catalog. Authored and validated there, published to Cloudflare R2. See [DataPatches.md](DataPatches.md).
- **[pindata](https://github.com/deanmoses/pindata)** — the canonical **seed catalog** source records: one Markdown file per entity (YAML frontmatter + prose), validated against JSON schemas. Originally bulk-ingested to bootstrap the database; flipcommons no longer ingests it directly. It remains a source repo for catalog facts and for pinexplore.
- **[pinexplore](https://github.com/deanmoses/pinexplore)** — read-only analysis. Builds a DuckDB database from pindata records plus external dumps (Wikidata, IPDB, OPDB etc) and runs integrity checks, cross-source comparisons and gap analysis. Not part of the serving path.

### Local layout convention

By convention, these repos live side by side under one parent directory on localhost dev, so `../pindata`, `../flippatch` and `../pinexplore` resolve from this repo. Tooling and docs assume that layout when they reference a sister project by relative path.

## How data reaches the database

A database starts from a **baseline** loaded with Django's database export/import (`manage.py dumpdata` / `loaddata`, or a copied SQLite/Postgres snapshot) — that's how a fresh dev DB is populated and how prod is restored. There is no seed-ingest of external sources.

On top of that baseline, every ongoing change — corrections and source updates — is a small, numbered [data patch](DataPatches.md), attributed to the source the fact came from. Patches are the only bulk write path; they are append-only and idempotent (already-applied ones are skipped), and a database stays current by applying whatever patches are pending. Applying them is always manual — there is no auto-ingest on deploy or startup. See [DataPatches.md](DataPatches.md).

```bash
make pull-patches     # fetch flippatch's data patches from R2
make ingest-patches   # apply pending patches (idempotent)
```

## Refreshing localhost DB from prod

`scripts/prod-to-sqlite.sh` rebuilds the local `db.sqlite3` from the current production database. User PII is scrubbed.

The script exempts a few developers from the PII scrub — their usernames are listed in [`scrub_prod_dump.py`](../backend/apps/accounts/management/commands/scrub_prod_dump.py) — and carries their WorkOS link forward so they can sign back in as Django admins.

## Postgres

[Refreshing localhost DB from prod](#refreshing-localhost-db-from-prod) leaves a prod-shaped PII-scrubbed Postgres container (`flipcommons-postgres`) on `127.0.0.1:5433`. Use it to test migrations and anything else SQLite can't represent.

SQL prompt — there is no `psql` on the host, so `manage.py dbshell` won't work:

```bash
docker exec -it flipcommons-postgres psql -U postgres
```

Point Django at it:

```bash
DATABASE_URL='postgresql://postgres:dev@127.0.0.1:5433/postgres' uv run --project backend python backend/manage.py migrate  # pragma: allowlist secret
```

## I want to…

- **Ask an empirical question about the current local catalog** → the [read-only DuckDB analysis foundation](../scripts/analysis/README.md) can answer it (its README covers both ad-hoc queries and doc-backing analyses).
- **Compare Flipcommons with external datasets** → use [pinexplore](https://github.com/deanmoses/pinexplore) (DuckDB, read-only).
- **Understand the catalog model** (titles, models, variants, manufacturers, taxonomy) → [DomainModel.md](DomainModel.md).
- **Correct or update a catalog value** → author a [data patch](DataPatches.md), attributed to the source the fact came from. Snapshot localhost first so you can iterate.
- **Bootstrap a fresh local database** → import a database export (Django `loaddata`, or copy a `db.sqlite3` snapshot).
- **Refresh localhost with current production data** → [`./scripts/prod-to-sqlite.sh`](#refreshing-localhost-db-from-prod); user PII is scrubbed on the way in.
- **Test a migration, or SQL that SQLite can't represent** → the [prod-shaped Postgres container](#postgres) the refresh script leaves running.
- **Apply pending corrections** to a running DB → `make pull-patches && make ingest-patches`.
- **Understand how a field's value is resolved** and audited → [Provenance.md](Provenance.md) (claims and resolution).
