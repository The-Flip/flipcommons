# Data Patches

A **data patch** is a small set of catalog claims authored as YAML and applied to a running database, without triggering a full re-ingest of the entire catalog's seed data. It's how you make a targeted, reproducible correction: author it, run it on localhost to check the effect, then run the identical file on production.

## The model: seed baseline, patches replayed on top

It's the schema-migration model, but for catalog data. The seed ingest is an **immutable baseline** we never edit to fix data. Corrections and ongoing source updates are **append-only, numbered patches replayed on top of the seed in every environment**: a fresh database reaches production's state by replaying seed → `0001` → `0002` → …. Production is seeded once, then patches arrive over time.

A patch is **attributed to a source** — usually `flipcommons-catalog`, Flipcommons' own attribution for values we research, scrape and classify ourselves (see [DataPatchAuthoring.md → Authoring a good patch](DataPatchAuthoring.md#authoring-a-good-patch)) — and does one of three things to _that source's_ claims:

- **assert / supersede** — (re-)assert a claim; the engine deactivates the source's prior claim for that `(entity, claim_key)` and writes the new one. Corrects a wrong value or carries a source's updated one.
- **create** — make a new entity and its claims.
- **retract** — deactivate the source's scalar/FK claim (the fact never existed or no longer does).
- **remove** — drop a relationship _member_ (a tag, a location) by superseding it with an `exists=false` tombstone. Distinct from retract: the claim stays active, resolving to "absent" — the same mechanism the in-app editor uses.
- **delete** — soft-delete an entity (the `status=deleted` lifecycle), distinct from a claim retract.

## Patches live in pindata

Data patches live in the [pindata](https://github.com/deanmoses/pindata) repo in the `patches/` directory. They are numbered files `NNNN-slug.yaml`, like `0001-prototype-tags`.

From there they are exported via pindata's `make pull-ingest` to R2, under the path `data/ingest_sources/pindata/patches/`.

## File format

Each patch file carries **one attribution** (→ one `IngestRun`).

### Edit

Edit an existing record:

```yaml
attribution: flipcommons-catalog # a Source slug; must already exist
description:
  > # The whole-patch "why" → IngestRun.note (only viewable in Django admin and git for now)
  Tag known unreleased prototypes.
claims: # ordered list of single-key entries
  - model.mazatron: # entity ref: <entity_type>.<public_id>
      expect: { year: 1990 } # drift guard (scalar + FK)
      note: 'IPDB says "exists only as a prototype machine".' # reason / evidence for the claims
      cite: ipdb:4443 # external evidence → citation on the claims
      production_status: unreleased # FK → target public_id
      tag: [prototype] # relationship: namespace → member public_ids
```

### Create

Create a new record:

```yaml
attribution: flipcommons-catalog
claims:
  - manufacturer.western-products:
      name: Western Products
      create: true # opt-in to create a missing entity
  - corporate-entity.western-products-incorporated:
      manufacturer: western-products # FK → public_id; resolves to the create above
```

`create: true` opts in to making a new entity — without it an unresolved ref errors; with it on a ref that already resolves, an error (duplicate). An FK target must already exist when the entry runs — in the seed, an _earlier_ patch, or **earlier in this same patch** — so a manufacturer and the corporate entity pointing at it can land together, the manufacturer declared first (a _forward_ reference, pointing at an entry below, isn't supported yet; see [Limitations](#limitations)). Creating a **Location** is the one create whose id is _derived_: write `slug` and `parent` as ordinary claims, and the `location_path` in the ref must compose from `parent + slug` (a mismatch errors).

### Retract

Deactivate a scalar/FK claim from this patch's source, on an existing entity:

```yaml
attribution: ipdb
claims:
  - corporate-entity.western-products-incorporated:
      retract: [manufacturer] # drop ipdb's manufacturer claim
```

It is attributed to the source whose claim it drops.

A no-op with a warning if the claim is already gone, so re-runs are safe. Not valid with `create:`, nor alongside asserting the same field. Retracting the sole claim of a non-nullable FK doesn't clear it (NOT NULL forbids it) — the last value freezes in place, provenance-orphaned; to _change_ a required FK, assert the new value instead. Because retract is scoped to this patch's source, attributing it to a source that never claimed the field silently does nothing — confirm which source holds the active claim first.

### Remove

Remove a relationship member:

```yaml
attribution: flip-museum # a museum-curated fact → flip-museum
claims:
  - corporate-entity.bally-wulff:
      location: [germany/berlin] # assert the more-specific member (exists=true)
      remove: { location: [germany] } # supersede the coarse member (exists=false)
      note: "Headquartered in Berlin, not just Germany."
```

This is the relationship counterpart of `retract:` (which is scalar/FK only). Above it refines a coarse `germany` location to `germany/berlin`. It is **not** a retraction: it supersedes this source's `exists=true` membership claim with an `exists=false` tombstone — the same write the in-app editor makes to drop a member — so the claim stays active and provenance (`note:`/`cite:`) rides it. Attribute it to the source holding the active membership claim (the resolver unions `exists=true` across sources):

A member this source doesn't currently claim present is a no-op with a warning (so re-runs are safe), not an error — but a no-op emits no tombstone, so an entry whose _only_ effect is a no-op removal can't anchor a `note:`/`cite:` and is rejected (the provenance would silently vanish). Not valid with `create:`/`delete:`, nor removing a member the same entry also asserts present. Relationship `remove:` is the only relationship retraction path — plain `retract:` rejects a relationship namespace.

### Delete

Soft-delete an entity:

```yaml
attribution: flipcommons-catalog
claims:
  - corporate-entity.chicago-coin-machinery-company:
      expect: { manufacturer: chicago-coin } # guard the row you're deleting
      delete: true
      note: "Duplicate of chicago-coin; its sole machine was reassigned first."
```

This writes a `status=deleted` claim (no row removal), exactly like an in-app delete. It reuses the app's soft-delete planner, so it obeys the same record-lifecycle rules: it **refuses** while an active PROTECT referrer would be left dangling — reassign any such referrer in an **earlier** patch first (the referrer check reads live DB state — see [Limitations](#limitations)) — and **cascades** `status=deleted` to owned lifecycle children (a warning lists them). A delete entry takes only `expect:`/`note:`/`cite:` — no field assertions, no `create:`, no `retract:`; `note`/`cite` ride the `status=deleted` claim. Idempotent: re-deleting an already-deleted entity diffs as unchanged. It takes effect only if the `status=deleted` claim wins resolution, so attribute it to a source that outranks any existing `status` claim.

### Entity references

Entity references are of format `type.public_id` — the canonical `entity_type` (`model`, `manufacturer`, `corporate-entity`, …) and the public id (slug for most, `location_path` for Location), split on the first `.`.

### Field keys

Field keys are classified by introspection: **scalar** (`year`) — value used as-is; **FK** (`manufacturer`, `production_status`) — value is the target's `public_id`; **relationship** (`tag`, `theme`, `manufacturer_alias`, `abbreviation`) — key is the namespace, value a list of members (FK public_ids, or bare strings for aliases/abbreviations). The lifecycle field **`status` is not directly assertable** — a raw `status: deleted` would skip the delete planner's blocker check and cascade, so it's rejected; soft-delete via `delete: true` instead.

Distinct from field keys are the **reserved keys** — directives, not claims: `create:`, `delete:`, `retract:` and `remove:` (each covered with its operation above), plus the cross-cutting `expect:`, `note:`, `cite:` and `cites:` (below).

### Aliases & abbreviations

Aliases and abbreviations are sets/arrays:

```yaml
attribution: flipcommons-catalog
claims:
  - manufacturer.stern:
      manufacturer_alias: [Stern Pinball, Stern Inc, Stern Electronics] # known trade names
  - model.medieval-madness:
      abbreviation: [MM, MedMad] # shared Title/MachineModel namespace
      remove: { abbreviation: [MedievalMadness] } # drop a bad earlier abbreviation
```

The field key is the **literal registered namespace** (`manufacturer_alias`, `abbreviation`); members are bare strings, not public_ids (alias values case-fold for identity, original case preserved for display; abbreviations are verbatim). Aliases and abbreviations need no `note:`/`cite:`. `remove:` drops a member the same way it drops an FK member.

### Drift guard

`expect:` is a drift guard: a map of currently-resolved values the target must already have, checked before any write (mismatch → error). Covers scalar + FK. It stops a hand-authored id from writing to a drifted or same-named row — guard every entry with it.

```yaml
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      expect: { ipdb_id: 4032 } # write only if this row already resolves to IPDB 4032
      production_status: produced
```

### Notes & citations

Write a `note:` about the changeset and `cite:` citations:

```yaml
attribution: flipcommons-catalog
claims:
  - model.mazatron:
      note: 'IPDB says "exists only as a prototype machine".' # the per-entity "why"
      cite: ipdb:4443 # scheme:identifier — dedups through the seeded IPDB root
      production_status: unreleased
  - model.medieval-madness:
      note: 'Wikipedia says it "was released in 1997".'
      cite: https://en.wikipedia.org/wiki/Medieval_Madness # raw URL — needs a seeded website root (see Citation sources)
      year: 1997
```

`note:` is the entity's ChangeSet note, shown on its Edit History page.

`cite:` is external evidence, attached to each of the entry's authored claims and shown beside the field on the edit-history page, in one of two forms:

- **`scheme:identifier`** (`ipdb:4443`, `opdb:GRhX5`) — a known scheme. Get-or-creates the source under that scheme's seeded root.
- **a `http(s)://` URL** (`https://en.wikipedia.org/wiki/...`) — any other web page. The URL's domain must match a **seeded website root** (a parentless web source whose homepage link shares the domain); the cite get-or-creates a `reference` child page under that root, keyed by the exact URL (re-citing reuses it). If no root matches, the patch errors — declare the website root in this patch's `sources:` block (processed before claims) or an earlier patch. (A root web source is an abstract container, so a patch never mints a parentless one.) A URL matching a known scheme's record pattern (e.g. an `ipdb.org/machine.cgi?id=...` link) is **rejected** — cite it as `scheme:identifier` so it dedups through the scheme path.

Two rules tie note/cite to the single changeset an entry produces:

- **One provenance-bearing entry per entity.** Two entries resolving to the same entity that both set `note`/`cite` is an error — combine them into one.
- **Provenance rides only an actual write (v1).** note/cite attach to what the patch writes. An entry with nothing to attach to (retraction-only, field-less create, empty `tag: []`) is a hard error. And re-asserting a value the entity already has from the same source diffs as unchanged — no claim, no changeset — so its `note`/`cite` are **silently dropped though the patch reports success**. To record provenance, the entry must change a value or create the entity.

### Inline citations in descriptions

A markdown field (a `description`) can carry **inline footnotes** — an `[[cite:…]]` marker placed after a fact, backing the nearby sentence, rendered as a numbered `[1]` footnote. Each distinct footnote is one `CitationInstance` that **floats** (`claim=null`): it's evidence for a passage, not for the whole field, so it isn't tied to any one claim. Markers reference that instance by its handle — repeat a handle and both markers point at the one footnote. A marker comes in two forms, told apart by its handle's grammar:

- **A new footnote** uses a **numeric handle** (`[[cite:1]]`) declared in a `cites:` map on the same entry. The handle is an ephemeral authoring label wiring the marker to its source; it is minted to a durable citation at apply time. Handles are arbitrary **all-digit** labels with **no ordering or contiguity** requirement (`1`, `2` is convention, not a rule) and a handle is **not** the rendered footnote number (render numbers by order of first appearance). A handle may repeat — two `[[cite:1]]` markers point at the one footnote.
- **An existing footnote** uses the citation's durable **slug** (`[[cite:bqntvkrs]]`) and needs **no** `cites:` entry — it self-resolves. This is the re-edit form you get from rehydration (below).

First authoring — new citations via numeric handles plus a `cites:` map:

```yaml
attribution: flipcommons-ai-desc-model
claims:
  - model.mazatron:
      expect: { ipdb_id: 4443 }
      description: >
        A 1990 solid-state prototype by Mac Pinball.[[cite:1]]
        Only two units are known to survive.[[cite:2]]
      cites:
        "1": ipdb:4443
        "2": https://pinside.com/thread
      note: "Narrative compiled from IPDB and Pinside."
```

`cites:` declares **only new** citations. Each key is a **numeric handle quoted as a string** (`"1":`, never bare `1:` — an unquoted integer key is a hard parse error) and each value is a cite-spec in the **same v1 grammar as `cite:`** — `scheme:identifier`, an `http(s)://` URL or a `{ url, archive }` map (per-citation locators are deferred to v2). The spec resolves through the same source get-or-create as `cite:`, so a URL still needs its [website root seeded](#citation-sources).

**Marker ↔ map correspondence is enforced** (a structural error, no DB lookup): every numeric-handle marker must have a `cites:` entry, and every `cites:` key must be a numeric handle referenced by at least one marker. A `cites:` entry keyed by a slug, or one no marker references, is a misuse. A marker that is neither all-digits nor a bare slug — notably a raw `[[cite:id:1]]` (storage form) — is rejected.

**Inline `cites:` count as provenance**, so the [one-provenance-bearing-entry-per-entity rule](#notes--citations) applies: an entity's cited description must live in a **single entry** — two entries on the same entity where either carries `cites:` (or `note:`/`cite:`) are rejected ("combine them into one entry").

Re-edit (rehydrated) — markers carry durable slugs, untouched cites need no `cites:`:

```yaml
attribution: flipcommons-ai-desc-model
claims:
  - model.mazatron:
      description: >
        A 1990 solid-state prototype manufactured by Mac Pinball.[[cite:bqntvkrs]]
        Only two units are known to survive.[[cite:mwzfprhd]]
      note: "Reworded the first sentence."
```

Re-applying a description with only existing slugs mints nothing and produces byte-identical storage, so it diffs as a no-op — reword one sentence and resubmit with every other citation intact. Generate this shape with [`dump_patch_entry`](DataPatchAuthoring.md#rehydrating-a-description-for-re-edit) rather than hand-copying slugs.

Two limitations to know:

- **`--dry-run` skips validating an assertion that references any new handle** (the slug isn't minted yet, so conversion can't resolve it). Such an assertion is counted but not diffed; its existing-slug portion isn't dry-validated either. Real validation is the snapshot+apply loop.
- **A bad or stale slug fails at apply with a _generic_ message** — `"N claim(s) failed validation"` live, `"Invalid claim: …"` in dry-run. The specific `Cite not found: [[cite:<slug>]]` only reaches the logs, so don't expect a friendly per-marker error.

### Strict parsing

Duplicate keys error, and values must be JSON-shaped — YAML coercion is off, so a bare `1996-01-01` stays a string and `no` stays `"no"`. A `note:` containing `"` needs YAML quoting (single-quote the value, as in the examples above).

## Citation sources

A patch can also create **citation sources** — the reference works (`ipdb`, `pinside`, a manufacturer's site) that `cite:` points at — via a top-level `sources:` block. Use it to add a new web/book/magazine root without editing the seed file. Unlike claims, a source is _not attributed_ and carries no provenance; `attribution:` still names the source that owns the run's ledger entry, not the citation sources.

```yaml
attribution: flipcommons-catalog # owns the IngestRun; does NOT attribute the sources
sources: # processed before claims, so a cite: below can nest under a root created here
  - name: Wikipedia
    source_type: web # book | magazine | web
    description: Free collaborative encyclopedia.
    links: # a source may carry several
      - {
          url: "https://en.wikipedia.org/",
          label: Wikipedia,
          link_type: homepage,
        }
      - {
          url: "https://de.wikipedia.org/",
          label: Wikipedia (Deutsch),
          link_type: homepage,
        }
claims: [] # optional — a sources-only patch is valid
```

A `sources:` node is the seed-data source shape (`name`, `source_type`, optional `author`/`publisher`/`year`/`month`/`day`/`date_note`/`isbn`/`description`/`identifier_key`, and `links`). **v1 is flat** — nested `children` is rejected; a child source under a root is created on demand when you `cite:` a URL on its domain.

**Identity and the get-or-create policy.** A source has no slug; identity is `isbn` if present, else `(name, source_type)`. The block is **additive get-or-create**, never an overwrite:

- not found → create the source and its declared links.
- found → leave the existing row untouched (a divergent declared field is a **warning**, not an error), and **additively backfill** any declared link the row is missing — so a later `cite:` can nest under the root even when the row already existed without your `homepage` link. An existing link with the same URL but a different `link_type`/`label` is left as-is and warned.
- two-plus rows match `(name, source_type)` → operate on the first, warn.

This is deliberate: a user can create a source through the app, so a same-identity collision is invisible when you author the patch. A strict "differs → error" policy would let one such collision **fail the patch and dam every later patch on prod** (patches stop at the first failure). Get-or-create never wedges and never clobbers user data — at the cost that, on a collision, the patch's description/links don't win (correctable only in Django admin). Because it's additive, re-applying is a clean no-op.

**What still hard-errors** (all author-controllable, and all surface at `--dry-run` on localhost before you ship): an unknown key, a nested `children`, a missing `name`/`source_type`, and any value the model rejects — a bad `source_type`, an out-of-range `year`/`month`/`day`, an invalid `identifier_key` or `link_type`, a malformed URL, or a duplicate declared link URL.

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

To test-and-revise a patch on localhost before shipping, snapshot the DB first — see [DataPatchAuthoring.md → Validate via snapshot](DataPatchAuthoring.md#validate-via-snapshot).

### Full ingest also applies patches

`make ingest-all`, the fresh-DB data bootstrap, also runs `ingest_patches`, to get the DB into something approximating production: seed, then the replayed patch log.

## The ledger: applied once, immutably

A patch application **is** an ingest run. Each `IngestRun` carries the `patch_id` (filename stem) and an `input_fingerprint` (sha256 of the normalized parsed content — comments, whitespace and key order ignored). The applied set is the `SUCCESS` runs with a `patch_id`, tracked **per database** (what makes "run locally, then on prod" work). On re-run: fingerprint matches → skip (a cosmetic reformat still skips); fingerprint differs → **hard error**, since an applied patch is immutable — a semantic change means you changed history, so add a new numbered patch instead. The invariant is enforced by a partial unique index on `patch_id` where `status='success'`, flipped in the same transaction as the claims.

On localhost, snapshot the DB before applying (see [DataPatchAuthoring.md → Validate via snapshot](DataPatchAuthoring.md#validate-via-snapshot)) so you can roll back and re-apply a revised patch rather than fighting this guard.

## Undoing a patch

There's no automatic revert; source-attributed claims aren't user-revertible. Undo a patch with a **compensating patch** (a later claim supersedes the earlier one).

On localhost, the simplest undo is restoring a pre-apply snapshot (see [DataPatchAuthoring.md → Validate via snapshot](DataPatchAuthoring.md#validate-via-snapshot)) — the compensating-patch rule is for seeded/shared databases whose history can't be rewound.

## Limitations

We've been building the patch system on an as-needed basis. These haven't been implemented yet.

- **No same-patch reassign-then-delete** — a `delete:`'s referrer check reads live DB state, so a reference reassigned earlier in the _same_ patch isn't yet visible; reassign in an earlier numbered patch, then delete.
- `expect:` covers scalar + FK only, not relationships. (`retract:` is scalar/FK; relationship members are dropped with `remove:`.)
- Relationship `remove:` covers **single-identity** relationships — single-FK members (`tag`, `location`, `theme`) and single string members (aliases, `abbreviation`). Multi-key relationships (e.g. credits) aren't yet removable via patch.
- **Single-identity relationships are writable** — both single-FK members (`tag`, `location`, `theme`, …, whose member is an FK to another entity) and single **string** members (`manufacturer_alias` and the other alias namespaces, `abbreviation`), whose member is a bare string. Alias values **case-fold** for identity (the original case is preserved for display); abbreviations are stored verbatim. **Multi-key** relationships (e.g. credits, person + role) remain unsupported.
- **No forward same-patch references.** A reference — an FK on a `create` or edit, a location `parent`, or a relationship member (`tag`, `location`, …) — resolves against the seed, an earlier patch, or an entry **earlier in this same patch**. What it can't yet do is point _forward_ at an entry declared **below** it: declare the target (manufacturer, title, tag, parent location, …) above its reference, or in an earlier patch. (Citing a `sources:`-declared website root in the same patch always works regardless of order — the source block is processed before claims.)
- **Parent hierarchies stay acyclic.** The self-referential parent relationships (`theme_parent`, `gameplay_feature_parent`) reject a self-link or a cycle, same as the in-app editor. The check is conservative: it weighs the patch's added edges against the current resolved graph and ignores `remove:`, so a patch that both detaches and re-attaches around the same edge may be over-rejected — split it across patches.
