# Data Patches

A **data patch** is a small set of catalog claims authored as YAML and applied to a running database, without triggering a full re-ingest of the entire catalog's seed data. It's how you make a targeted, reproducible correction: author it, run it on localhost to check the effect, then run the identical file on production.

## The model: seed baseline, patches replayed on top

It's the schema-migration model, but for catalog data. The seed ingest is an **immutable baseline** we never edit to fix data. Corrections and ongoing source updates are **append-only, numbered patches replayed on top of the seed in every environment**: a fresh database reaches production's state by replaying seed → `0001` → `0002` → …. Production is seeded once, then patches arrive over time.

A patch is **attributed to the source making the claim** (which may be `flipcommons-catalog` when we derive structured data from another source's prose — see [Authoring a good patch](#authoring-a-good-patch)) and does one of three things to _that source's_ claims:

- **assert / supersede** — (re-)assert a claim; the engine deactivates the source's prior claim for that `(entity, claim_key)` and writes the new one. Corrects a wrong value or carries a source's updated one.
- **create** — make a new entity and its claims.
- **retract** — remove the source's claim (the fact never existed or no longer does).

## File format

Numbered files `NNNN-slug.yaml` like `0001-prototype-tags`. They live in the [pindata](https://github.com/deanmoses/pindata) repo under `patches/` and ride the R2 export → `make pull-ingest` path to `data/ingest_sources/pindata/patches/`. One patch carries **one attribution** (→ one `IngestRun`).

```yaml
attribution: flip-museum # a Source slug; must already exist
description:
  > # optional; the whole-patch "why" → IngestRun.note (only viewable in Django admin and git for now)
  Tag known unreleased prototypes.
claims: # ordered list of single-key entries
  - model.mazatron: # entity ref: <entity_type>.<public_id>
      expect: { year: 1990 } # drift guard (scalar + FK)
      note: 'IPDB says "exists only as a prototype machine".' # reason / evidence for the claims
      cite: ipdb:4443 # external evidence → citation on the claims
      production_status: unreleased # FK → target public_id
      tag: [prototype] # relationship: namespace → member public_ids
```

Create + supersede, attributed to the source whose value it corrects:

```yaml
attribution: flipcommons-catalog
claims:
  - manufacturer.western-products:
      name: Western Products
      create: true # opt-in to create a missing entity
  - corporate-entity.western-products-incorporated:
      manufacturer: western-products # FK → public_id; supersedes this source's prior claim
```

Creating a **Location** is the one create whose public id is _derived_ rather than authored: `location_path` is built from `parent` + `slug`. Write `slug` and `parent` as ordinary claims; the adapter takes the path from the entity reference, never claims it, and verifies it composes from `parent + slug` (a mismatch is an error). The `parent` must already exist (an earlier patch or the seed) — a parent created in the same patch isn't resolvable yet. Omit `parent` for a root (country).

```yaml
attribution: flip-museum
claims:
  - location.usa/tx/paris: # location_path = parent + slug
      create: true
      name: Paris
      slug: paris # the claim-based form input
      parent: usa/tx # FK by location_path; must already exist
      location_type: city
```

Retract, attributed to the source whose claim it removes:

```yaml
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer] # drop ipdb's manufacturer claim
```

**Entity reference** is `type.public_id` — the canonical `entity_type` (`model`, `manufacturer`, `corporate-entity`, …) and the public id (slug for most, `location_path` for Location), split on the first `.`.

**Field keys** are classified by introspection: **scalar** (`year`) — value used as-is; **FK** (`manufacturer`, `production_status`) — value is the target's public_id; **relationship** (`tag`, `theme`) — key is the namespace, value a list of member public_ids.

**Reserved keys** (directives, not claim fields):

- `create: true` — opt-in to create. Unresolved ref without it → error; resolved ref with it → error (duplicate).
- `expect:` — drift guard: a map of currently-resolved values the target must already have, checked before any write (mismatch → error). Covers scalar + FK. Stops a hand-authored id from writing to a drifted or same-named row.
- `retract:` — scalar/FK field names whose claim (from this patch's source) to deactivate, on an existing entity. A no-op with a warning if already gone, so re-runs are safe. Not valid with `create`, nor alongside asserting the same field. Retracting the sole claim of a non-nullable FK doesn't clear it (NOT NULL forbids it) — the last value freezes in place, provenance-orphaned; to _change_ a required FK, assert the new value instead. Because it is scoped to this patch's source, attributing the retract to a source that never claimed the field silently does nothing — confirm which source holds the active claim first.
- `note:` — a per-entity free-text reason (≤1000 chars) → the entity's ChangeSet note, shown on its edit-history page. (`description:` explains the whole patch; `note:` explains one entry.) All of an entity's claims in a patch collapse into one changeset, so the note is per-entity. The per-entity `note:` is the user-facing one; the whole-patch `description:` (→ `IngestRun.note`) is, as of this writing, surfaced only in Django admin — so put anything readers should see in `note:`, not `description:`.
- `cite:` — external evidence as `scheme:identifier` (`ipdb:4443`, `opdb:GRhX5`). Get-or-creates the source under that scheme's root and attaches a citation to each of the entry's authored claims, shown beside the field on the edit-history page.

Two rules tie note/cite to the single changeset an entry produces:

- **One provenance-bearing entry per entity.** Two entries resolving to the same entity that both set `note`/`cite` is an error — combine them into one.
- **Provenance rides only an actual write (v1).** note/cite attach to what the patch writes. An entry with nothing to attach to (retraction-only, field-less create, empty `tag: []`) is a hard error. And re-asserting a value the entity already has from the same source diffs as unchanged — no claim, no changeset — so its `note`/`cite` are **silently dropped though the patch reports success**. To record provenance, the entry must change a value or create the entity.

**Strict parsing:** duplicate keys error, and values must be JSON-shaped — YAML coercion is off, so a bare `1996-01-01` stays a string and `no` stays `"no"`. A `note:` containing `"` needs YAML quoting (single-quote the value, as above).

## Authoring a good patch

- **Attribute to whoever makes the claim.** A value the source itself states → that source (`ipdb`, `opdb`); correcting it → still that source, so you supersede or retract _its_ claim. A structured value _we derive_ by classifying a source's free text (the source has no such field — e.g. parsing IPDB notes into a `game_format`) → `flipcommons-catalog`, with `cite:` to the source text as evidence; there's no source claim to supersede. Museum-curated facts no one else claims → `flip-museum`.
- **One entity per entry**, carrying all its fields and its single `note`/`cite`.
- **Create vocabulary in an earlier patch.** A `tag:` member or FK target must already exist when the entry runs, and same-patch resolution works for FK fields only. Put new tags/statuses in an earlier numbered patch, then reference them — e.g. one patch creates the `aftermarket` status and re-theme tags, the next assigns them.
- **Guard every entry with `expect:`** against a current resolved value — `year`, or another stable field like `corporate_entity` when year is null — so a typo'd or drifted public_id fails loudly instead of writing to the wrong row. When claims are keyed off an external record (IPDB/OPDB), guard on that id — `expect: { ipdb_id: 4965 }`: it's the most specific guard, it's the same record your `cite:` points at, and it's present even when `year` and `corporate_entity` are both null.
- **Explain every change with `note:`**, written as `<source> says "<verbatim quote>"`. Quote the source _verbatim_, mark your own omissions with `[...]`, and keep it _plain ASCII_ (no smart quotes or `…`).
- **Cite external evidence with `cite:`** (IPDB/OPDB records). Skip the citation when the evidence is in the entity's own data and instead write it in the note such as "Its name contains the word 'prototype'". The cite can also differ from the `expect:` guard: when the evidence lives in a _different_ record's note (a cross-reference — "‹other game› is not a pinball"), guard on the model's own id but `cite:` the record that contains the statement.
- **Only assert what a source supports.** If you can't point to evidence, leave the field unset rather than guess: an unset value reads as "unknown", a wrong claim reads as fact.
- **Large curated patches: keep a worksheet, emit from a script.** For a patch spanning dozens of curated rows, record every search you ran (including the ones that found nothing) and the verbatim source text behind each call in a review worksheet, then generate the YAML from a script that reads live field values for the `expect:` guards. Hand-copying guards drifts from the DB; a generator keeps them true and the worksheet keeps the editorial judgment auditable. The dead-end searches matter too — proving a term is absent from the sources is what justifies relying on the signal you did find. **Don't reinvent the generator** — follow [DataPatchAuthoring.md](DataPatchAuthoring.md) and use the shared `patchkit` helper (escaping, `expect:` guards, source-text extraction).
- **Dry-run, then localhost, then prod** — see below.

## Applying patches

Patches don't auto-apply; there's no deploy or startup hook — you run the command manually. Applying patches is the everyday correction path once a database is seeded (production never re-ingests the seed data).

Run `make pull-ingest` first to fetch new patch files:

```bash
# Everyday path — applies pending patches from the default dir
# (data/ingest_sources/pindata/patches/):
make ingest-patches

# That just wraps the management command. Run the mgt cmd directly to preview or
# point at another directory:
cd backend
uv run python manage.py ingest_patches --dry-run          # preview; no writes
uv run python manage.py ingest_patches --patches-dir DIR  # override the default dir
```

Patches apply in numeric order. The command **pre-flights the whole batch** (filename format, unique numeric prefixes), then **stops at the first failure** — patches before it stay committed, the failing one and everything after are left unapplied. A missing or empty directory is a no-op. It is idempotent — the ledger skips already-applied patches.

### Iterating on localhost: snapshot first

Because an applied patch is immutable per-database (see [The ledger](#the-ledger-applied-once-immutably)), you can't tweak a patch and re-run it against a DB that already has it — the fingerprint guard hard-errors. To test-and-revise on localhost, snapshot the SQLite file before applying and restore it to roll back:

```bash
cd backend
cp db.sqlite3 db.pre-0009.sqlite3          # snapshot before applying patch 0009
uv run python manage.py ingest_patches
# inspect the effect in the running app / Django admin
# wrong? roll back, edit the patch, re-apply:
cp db.pre-0009.sqlite3 db.sqlite3
```

`--dry-run` previews without writing; the snapshot loop is for when you want to apply for real, browse the resolved result, then revert. Name the snapshot after the patch you're about to apply (`db.pre-NNNN.sqlite3`) so it's clear which state it captures; the `.sqlite3` suffix keeps it under the gitignored `*.sqlite3` rule, so it won't be committed. Once the patch is right, it's safe to push to prod.

### Full ingest also applies patches

`make ingest-all`, the fresh-DB data bootstrap, also runs `ingest_patches`, to get the DB into
something approximating production: seed, then the replayed patch log.

## The ledger: applied once, immutably

A patch application **is** an ingest run. Each `IngestRun` carries the `patch_id` (filename stem) and an `input_fingerprint` (sha256 of the normalized parsed content — comments, whitespace and key order ignored). The applied set is the `SUCCESS` runs with a `patch_id`, tracked **per database** (what makes "run locally, then on prod" work). On re-run: fingerprint matches → skip (a cosmetic reformat still skips); fingerprint differs → **hard error**, since an applied patch is immutable — a semantic change means you changed history, so add a new numbered patch instead. The invariant is enforced by a partial unique index on `patch_id` where `status='success'`, flipped in the same transaction as the claims.

On localhost, snapshot the DB before applying (see [Iterating on localhost](#iterating-on-localhost-snapshot-first)) so you can roll back and re-apply a revised patch rather than fighting this guard.

## Undoing a patch

No automatic revert — source-attributed claims aren't user-revertible. Undo a patch with a **compensating patch** (a later claim supersedes the earlier one).

On localhost, the simplest undo is restoring a pre-apply snapshot (see [Iterating on localhost](#iterating-on-localhost-snapshot-first)) — the compensating-patch rule is for seeded/shared databases whose history can't be rewound.

## Limitations

We've been building the patch system on an as-needed basis. These haven't been needed yet.

- **No entity delete** — distinct from a claim retract; the status=deleted lifecycle.
- `expect:` and `retract:` only cover scalar + FK, not relationships.
- Same-patch references resolve for **FK fields only**: an FK can point at an entity created earlier in the same patch, but a relationship member (e.g. `tag:`) must already exist in the DB.
