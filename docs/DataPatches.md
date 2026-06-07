# Data Patches

A **data patch** is a small, source-attributed set of catalog claims authored as YAML, applied to a running database without a full re-ingest. Patches are the way to make a targeted, reproducible correction to live catalog data: author it, run it on localhost to see the change, then run the identical patch on production.

A patch is just _a small set of source-attributed claim operations_ — it rides the existing claims + ingest machinery, not a parallel engine.

## The model: seed baseline, patches replayed on top

This is the schema-migration model, for data. The seed ingest is an **immutable baseline**; we never edit it to fix data. Corrections and ongoing source updates are **append-only, numbered patches replayed on top of the seed in every environment**. A fresh database reaches production's state by replaying: **full ingest = seed ingest, then `ingest_patches`** (seed → `0001` → `0002` → …). Production is seeded once, then patches arrive over time.

A patch is **attributed to the source the fact came from** and performs one of three operations against _that source's_ claims:

- **assert / supersede** — re-assert a claim under the source; the engine deactivates the source's prior claim for that `(entity, claim_key)` and writes the new one. Corrects a wrong value (`flipcommons-catalog` now says X) or carries a source's updated value (OPDB changed Y).
- **create** — make a new entity and its claims under the source.
- **retract** — remove the source's claim entirely (the fact no longer exists or never did).

There is **no "override tier."** We don't outrank a wrong claim with a higher-priority editorial claim — we correct the erring source directly (supersede or retract). Priority still resolves _genuine_ cross-source disagreement.

## File format

Patches are numbered files named `NNNN-slug.yaml`. The numeric prefix orders application; the filename stem (`0001-prototype-tags`) is the **patch id**. They live in the [pindata](https://github.com/deanmoses/pindata) repo under `patches/` and ride the existing R2 export → `make pull-ingest` path, landing at `data/ingest_sources/pindata/patches/`.

One patch carries **one attribution** (→ one `IngestRun`). An edit patch:

```yaml
attribution: flip-museum # a Source slug; must already exist
description: > # optional; copied to the IngestRun note
  Why this change is being made.
claims: # ordered list of single-key entries
  - model.mazatron: # entity ref: <entity_type>.<public_id>
      expect: { year: 1990 } # optional drift guard (scalar + FK)
      tag: [prototype] # relationship: namespace → list of public_ids
```

A create + supersede patch, attributed to the source whose value it corrects:

```yaml
attribution: flipcommons-catalog
claims:
  - manufacturer.western-products:
      name: Western Products
      create: true # opt-in to create a missing entity
  - corporate-entity.western-products-incorporated:
      manufacturer:
        western-products # FK → target public_id; supersedes this
        # source's prior manufacturer claim
```

A retract patch, attributed to the source whose fabricated claim it removes:

```yaml
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer] # drop ipdb's manufacturer claim entirely
```

**Entity reference key** is `type.public_id`: the canonical `entity_type` (`model`, `manufacturer`, `corporate-entity`, …) and the entity's public identifier (slug for most, `location_path` for Location), split on the first `.`.

**Field keys** are classified by introspection:

- **scalar** (`year`, `production_quantity`) — value used as-is.
- **FK** (`manufacturer`, `title`) — value is the target's public_id.
- **relationship** — the key is the **namespace** (`tag`, `theme`), value is a list of member public_ids.

**Reserved keys** (not claim fields):

- `create: true` — explicit opt-in to create. Reference doesn't resolve and `create` absent → hard error. Reference already resolves + `create: true` → hard error (duplicate).
- `expect:` — drift guard. A map of currently-resolved values the target must already have, checked before any write; a mismatch is a hard error. Stops a hand-authored public_id from hitting a drifted or same-named row. v1 covers scalar + FK.
- `retract:` — a list of scalar/FK field names whose claim (from **this patch's source**) should be removed, on an existing entity. The engine deactivates the source's active claim for that key, then re-resolves; if no such claim exists it warns rather than errors, so a re-run is a no-op. Not valid together with `create`. You also can't both retract and assert the same field on one entity in the same patch (the assert would just re-add it) — that's rejected.

  **Required FKs don't go away.** Retracting the _sole_ claim of a non-nullable FK (e.g. `manufacturer`) does **not** clear the field — it can't, NOT NULL forbids it. The resolver freezes the last-resolved value in place, now backed by **no active claim** (provenance-orphaned). This avoids an `IntegrityError`, but it's rarely what you want: if you mean to **change** the value, just assert the corrected value — that supersedes this source's claim, no retract needed (and retracting plus asserting the same field is rejected). Retract a required FK only when **another source** still claims it and should take over.

**Strict parsing:** duplicate mapping keys are an error, and values must be JSON-shaped — YAML implicit coercion is disabled, so a bare `1996-01-01` stays a string and `no` stays `"no"` (no need to quote, but no surprises either).

## Applying

Manual and infrequent — no deploy or startup hook. Applying patches on their own is the everyday correction path once a database is seeded (production is never re-ingested); `make pull-ingest` first to fetch new patch files:

```bash
make ingest-patches                              # apply pending patches

cd backend
uv run python manage.py ingest_patches --dry-run  # report intended claims, no writes
uv run python manage.py ingest_patches --patches-dir DIR
```

Patches apply in numeric order. The command **pre-flights the whole batch** (filename format, unique numeric prefixes) before applying anything, then **stops at the first failure** — patches before it stay committed, the failing one and all after it are left unapplied. A missing or empty patches directory is a no-op.

`ingest_patches` also runs as the **tail of a fresh-DB bootstrap** (`make ingest-all` runs `ingest_all --write` then `ingest_patches`), so a brand-new database lands in the same state as production: seed, then the replayed patch log. It is idempotent — the ledger skips already-applied patches — so re-running is safe.

### Attribution and resolution priority

A patch must name an existing `Source`. A patch attributes to the source the fact came from and corrects _that source's_ own claim, so the only **new** source seeded for patches is:

- `flip-museum` (priority 10000, user tier) — museum-curated facts (e.g. the prototype list). It asserts new facts no other source claims, and at the user tier it resolves as a peer edit (newest wins, re-breakable).

Corrections attribute to the existing seed sources — `flipcommons-catalog` (priority 300), `ipdb`, `opdb` — and supersede or retract that source's claim directly. There is no editorial override source. Priority continues to resolve genuine cross-source disagreement.

Durability does **not** come from a patch surviving a re-ingest — it wouldn't. Because a correction is a same-source claim, re-running the seed re-asserts the original value and supersedes the patch (and the ledger then skips re-applying it). Durability comes instead from the operating model: live databases are seeded once and **never re-ingested** (they only run `ingest_patches`), and a fresh database replays **seed, then patches**, so the patch lands last and wins. See [Ingest.md](Ingest.md) for the prod ingestion vs. patch paths.

## The ledger: applied once, immutably

A patch application **is** an ingest run. Each `IngestRun` carries:

- `patch_id` — the filename stem (the applied-ledger key).
- `input_fingerprint` — a sha256 of the patch's **normalized parsed content** (canonical JSON; comments / whitespace / key order ignored).

The applied set is the `SUCCESS` runs with a `patch_id`, tracked **per database** — which is what makes "run locally, then run on prod" work. On re-run:

- **applied + fingerprint matches** → skip (a cosmetic reformat still skips).
- **applied + fingerprint differs** → hard error. An applied patch is **immutable**; a semantic change means you changed history — add a new numbered patch instead.

The "applied once" invariant is enforced in the database (a partial unique index on `patch_id` where `status='success'`), and the `SUCCESS` flip commits in the same transaction as the claims, so a torn write is never seen as applied.

## Undoing a patch

There is no automatic revert — source-attributed claims aren't user-revertible. Undo a patch with a **compensating patch** (a later claim supersedes the earlier one).

## Limits (v1)

- Create, edit (assert / supersede) and retract; **no entity delete** (the `status=deleted` lifecycle is distinct from a claim retract and is out of scope).
- Create requires a **claim-based public id** (`slug`). Entities whose public id is system-generated — e.g. `Location`, whose `location_path` is derived from its parent path plus its leaf `slug` — can't be created via a patch and are rejected with a clear error.
- `expect:` and `retract:` cover scalar + FK, not relationships.
- Same-patch references resolve for **FK fields only**: an edit can point an FK at an entity created earlier in the same patch (FK claims resolve by public_id after the creates run). **Relationship** members (e.g. `tag:`) are resolved against the DB eagerly, so a member created in the same patch is rejected — relationship targets must already exist. (Creating an FK target as part of a `create` entry is also unsupported.)
