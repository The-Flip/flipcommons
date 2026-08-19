# Data Patches

A **data patch** is a small set of catalog claims authored as YAML and applied to a running database, without triggering a full re-ingest of the entire catalog's seed data. It's how you make a targeted, reproducible correction: author it, run it on localhost to check the effect, then run the identical file on production.

## The model: a database baseline, patches replayed on top

It's the schema-migration model, but for catalog data. A database starts from a **baseline** loaded via Django's database export/import (`dumpdata`/`loaddata`, or a copied DB snapshot) — a fresh dev DB is populated this way, prod is restored from backup. The baseline is never edited by hand to fix data. On top of it, corrections and ongoing source updates are **append-only, numbered patches replayed in order in every environment** (`0001` → `0002` → …). Patches are never edited once applied; fixes arrive as new patches over time.

A patch is **attributed to a source** — usually `flipcommons-catalog`, Flipcommons' own attribution for values we research, scrape and classify ourselves (see [DataPatchAuthoring.md → Authoring a good patch](DataPatchAuthoring.md#authoring-a-good-patch)) — and does one of the following things to _that source's_ claims:

- **assert / supersede** — (re-)assert a claim; the engine deactivates the source's prior claim for that `(entity, claim_key)` and writes the new one. Corrects a wrong value or carries a source's updated one.
- **create** — make a new entity and its claims.
- **retract** — deactivate the source's scalar/FK claim (the fact never existed or no longer does).
- **remove** — drop a relationship _member_ (a tag, a location) by superseding it with an `exists=false` tombstone. Distinct from retract: the claim stays active, resolving to "absent" — the same mechanism the in-app editor uses.
- **delete** — soft-delete an entity (the `status=deleted` lifecycle), distinct from a claim retract.

## Patches live in flippatch

Data patches live in the [flippatch](https://github.com/deanmoses/flippatch) repo in the `patches/` directory. They are numbered files `NNNN-slug.yaml`, like `0001-prototype-tags`.

During localhost development, developers will have both projects checked out in sibling directories and can ingest in-progress patches to try them out using `--patches-dir` to point to the Flippatch patches directory. It'll be something like `../flippatch/patches/` though you might need an absolute path. Generally developers will already have a backup database, so that patches can be corrected and ingest run again.

## File format

Each patch file carries **one attribution** (→ one `IngestRun`), and each correction becomes its **own** `ChangeSet` — one note slot, rendered in file order on the entity's Edit History page (mirroring the in-app model, where each edit mints one ChangeSet). A single record usually needs several separately-cited corrections; the canonical form groups them under one header — the entity ref declared once — with a `changesets:` list, one item per `ChangeSet`, each carrying its own `note`/`cite` (see [Notes & citations](#notes--citations)).

### Edit

Group several corrections to one record under a single header — the ref declared once, a `changesets:` list beneath, one item per `ChangeSet`:

```yaml
attribution: flipcommons-catalog # a Source slug; must already exist
description:
  > # The whole-patch "why" → IngestRun.note (only viewable in Django admin and git for now)
  Correct the Mazatron prototype.
claims: # ordered list of single-key entries
  - model.mazatron: # entity ref: <entity_type>.<public_id>
      changesets: # each item is its own ChangeSet: its own evidence + field assertions
        - cite: # external evidence → citation on this item's claims
            ref: ipdb:4443
            quote: "exists only as a prototype machine" # the verbatim excerpt behind them
          production_status: unreleased # FK → target public_id
          tag: [prototype] # relationship: namespace → member public_ids
        - cite:
            ref: https://pinside.com/thread
            quote: "only two prototypes were built, in 1990"
          production_year: 1990 # a disjoint field with its own evidence → its own ChangeSet
```

Each `changesets:` item inherits the header's ref and becomes its own `ChangeSet`. Items carry **only field assertions plus provenance** (`note`/`cite`/`cites`/`retract`/`remove`) — lifecycle (`create:`/`delete:`) is header-only. The items' fields must be **disjoint**: two items can't both set `production_year` (see [Notes & citations](#notes--citations) for this and the rest of the per-entry rules).

For a record that needs just **one** correction, the flat single-key form is the shorthand — the body sits directly under the ref, no `changesets:` wrapper:

```yaml
attribution: flipcommons-catalog
claims:
  - model.mazatron:
      cite:
        ref: ipdb:4443
        quote: "exists only as a prototype machine"
      production_status: unreleased
```

(Repeating the flat single-key entry once per change on the same record — the shape that predates `changesets:` — still parses, but prefer the grouped form so the ref isn't duplicated.)

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

**Create then refine the same record in one file.** Hang companion edits off the create with a `changesets:` list — the `create: true` header makes the record, each item asserts _additional_ fields as its own separately-attributed `ChangeSet`:

```yaml
attribution: flipcommons-catalog
claims:
  - manufacturer.western-products:
      create: true # the header is the create
      name: Western Products
      changesets: # companion edits on the record just created
        - website: https://westernproducts.example
          note: "Company site, per the IPDB listing."
          cite: ipdb:1234
```

This is how one coherent change — a create plus a separately-cited refinement — lives in a single file instead of needing a follow-up patch (each item its own `ChangeSet` with its own `note`/`cite`). A companion takes **only field assertions**: `retract:` and `remove:` (there are no prior claims to drop) are each rejected, and per the [disjoint-fields rule](#notes--citations) it may not reassert a field the create already set.

The older shape — a flat `create:` entry followed by separate single-key companion entries on the same record — still parses, but it forced you to order the companions **below** the create by hand (an edit above its create errors); `changesets:` makes that ordering structural:

```yaml
attribution: flipcommons-catalog
claims:
  - manufacturer.western-products: # create the record
      name: Western Products
      create: true
  - manufacturer.western-products: # refine it — must sit below the create
      website: https://westernproducts.example
      note: "Company site, per the IPDB listing."
      cite: ipdb:1234
```

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
      delete: true
      note: "Duplicate of chicago-coin; its sole machine was reassigned first."
```

This writes a `status=deleted` claim (no row removal), exactly like an in-app delete. It reuses the app's soft-delete planner, so it obeys the same record-lifecycle rules: it **refuses** while an active PROTECT referrer would be left dangling — reassign any such referrer in an **earlier** patch first (the referrer check reads live DB state — see [Limitations](#limitations)) — and **cascades** `status=deleted` to owned lifecycle children (a warning lists them). The root and its cascade children land in a **single** ChangeSet, matching an in-app delete. A delete is **exclusive over that footprint**: no other entry in the patch may target the deleted entity or any of its cascade children. A delete entry takes only `note:`/`cite:` — no field assertions, no `create:`, no `retract:`; `note`/`cite` ride the `status=deleted` claim. Idempotent: re-deleting an already-deleted entity diffs as unchanged — the one no-op a provenance-bearing entry is allowed (see [Notes & citations](#notes--citations)). It takes effect only if the `status=deleted` claim wins resolution, so attribute it to a source that outranks any existing `status` claim.

### Entity references

Entity references are of format `type.public_id` — the canonical `entity_type` (`model`, `manufacturer`, `corporate-entity`, …) and the public id (slug for most, `location_path` for Location), split on the first `.`.

### Field keys

Field keys are classified by introspection: **scalar** (`production_year`) — value used as-is; **FK** (`manufacturer`, `production_status`) — value is the target's `public_id`, resolved to the target's PK at plan time (a patch's slugs are point-in-time: valid at apply, never stored in claims); **relationship** (`tag`, `theme`, `manufacturer_alias`, `abbreviation`) — key is the namespace, value a list of members (FK public_ids, or bare strings for aliases/abbreviations). The lifecycle field **`status` is not directly assertable** — a raw `status: deleted` would skip the delete planner's blocker check and cascade, so it's rejected; soft-delete via `delete: true` instead.

Distinct from field keys are the **reserved keys** — directives, not claims: `create:`, `delete:`, `retract:` and `remove:` (each covered with its operation above), the cross-cutting `note:`, `cite:` and `cites:` (below), the grouping key `changesets:` (see [File format](#file-format)).

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

### Counted members (gameplay features)

Most relationship members are a bare public_id (a `tag`, a `theme`). `gameplay_feature` is the one namespace whose members can also carry a **count** — "4 ramps", "3 flippers". Author the count with a **one-key `{public_id: count}` mapping** in place of the bare slug; mix the two forms freely in one list:

```yaml
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      gameplay_feature:
        - multiball # bare slug → count NULL
        - ramps: 4 # one-key mapping → count 4
```

Rules:

- If you supply a count, it must be **positive integer** (`>= 1`); it cannot be `0`, negative or non-int (`ramps: lots`). A bare `ramps:` parses as the empty string `''` and not null, so it's rejected.
- Only `gameplay_feature` takes a count. Other simple member relationships (`tag`, `theme`, `location`) reject the counted mapping form — `- prototype: 2` errors with "must be a public_id string". Structured relationships such as credits and model relationships use the mapping forms documented below.
- The count is **not part of member identity**: re-asserting a member with a new count supersedes the old one.

`remove:` uses the bare slug:

```yaml
claims:
  - model.medieval-madness:
      remove:
        gameplay_feature:
          - ramps
```

### Credits

A **credit** — "person X did role Y on this model or series" — has the two-part identity `{person, role}`. A credit member is written as a **single-key mapping** `<person-public_id>: <role-public_id>` — one line per credit, no braces. In YAML a list item `- brian-eddy: design` parses to the dict `{brian-eddy: design}`, so the **key is the person** public_id and the **value is the role** (a `credit-role`) public_id. The `credit:` value is a flat list of these, so a person can repeat — each list item is one `{person, role}` claim:

```yaml
attribution: flipcommons-catalog
claims:
  - model.medieval-madness:
      cite: ipdb:4032
      credit:
        - brian-eddy: design
        - john-youssi: art
        - dan-forden: software
        - dan-forden: sound # same person, second role → distinct claim
```

An entry-level `cite:`/`note:` rides each credit claim exactly as it does a scalar or FK claim. (The inline `[[cite:N]]` footnote form is markdown-field-only and doesn't apply — a credit carries no text.) Both the person and the role must already exist (in the seed, an earlier patch, or earlier in this same patch); a `credit-role` is creatable with `create: true` like any other taxonomy value.

> **Quote slugs YAML would read as non-strings.** A person or role slug that looks like a YAML boolean, null or number — `off`, `no`, `null`, `1979` — parses to a bool/null/int rather than a string and is rejected (loudly, never silently). Quote it: `- some-designer: "no"`.

Credits work on `series.*` entries as well as `model.*`:

```yaml
claims:
  - series.world-cup-soccer:
      credit:
        - pat-lawlor: design
```

**Same-patch create.** Either slot may reference an entity created earlier in the same patch — declare the `person` (or `credit-role`) above, then credit it below:

```yaml
claims:
  - person.jane-newcomer:
      create: true
      name: Jane Newcomer
  - model.some-game:
      credit:
        - jane-newcomer: art # resolves to the create above
```

**Remove** drops a credit member like any other relationship member — same single-key mapping, attributed to the source holding the membership claim:

```yaml
claims:
  - model.medieval-madness:
      remove:
        credit:
          - john-youssi: art
```

### Model relationships

A **model relationship** — "this model is a copy / conversion / conversion kit / re-theme of that machine" — is authored under `model_relationship:` as a list of **explicit-key mappings**. Each member names its target at exactly one of two resolutions — `target_machine` (a model public_id) XOR `target_label` (plain text for an unseeded or plural target) — plus two mandatory payload keys, `relationship_type` (`conversion` | `conversion_kit` | `copy` | `retheme`) and `license_status` (`licensed` | `unlicensed` | `unknown`):

```yaml
attribution: flipcommons-catalog
claims:
  - model.punky-willy:
      cite:
        ref: ipdb:4101
        quote: "This game is a copy of Premier's 1985 'Rock' and Premier's 1986 'Rock Encore'."
      model_relationship:
        - target_machine: rock
          relationship_type: copy
          license_status: unknown
        - target_machine: rock-encore
          relationship_type: copy
          license_status: unknown
  - model.sky-warrior:
      cite:
        ref: ipdb:3905
        quote: Conversion kit for many solid state Gottlieb games of the late 1970's.
      model_relationship:
        - target_label: many late 1970s solid state Gottliebs
          relationship_type: conversion_kit
          license_status: unknown
```

Rules:

- **Exactly one target key.** `target_machine` plus `target_label` on one member is rejected, as is a member with neither. Don't restate the machine's manufacturer in a label when `target_machine` is set — the model row already knows it.
- **Some types require a seeded machine target.** A `retheme` member must use `target_machine`; a `target_label` on a re-theme is rejected (a re-theme's donor is always a known, seeded machine). For re-themes, `license_status` records official (`licensed`) vs unofficial (`unlicensed`), or `unknown` when no source establishes it.
- **`license_status` is deliberately explicit** — there is no silent default in patches. Write `unknown` when no source establishes authorization either way; an unlicensed copy is `relationship_type: copy` + `license_status: unlicensed`, and the source must establish both facts.
- **Identity is the machine target only; a model holds one label slot.** Re-asserting a machine-target member with a different `relationship_type`/`license_status` supersedes the old values in place; two members with the same target in one entry are a duplicate and rejected. The label edge is keyed by its _slot_, not its wording: a model has at most one `target_label` edge, re-asserting one with different wording rewords that edge in place (same edge, citations intact) and a same-actor label assert in a later patch supersedes the earlier one rather than adding a second edge.
- **Same-patch create** works for `target_machine` like any FK member — create the model above, reference it below.

`remove:` names the edge by its identity; payload keys are rejected there. For a label edge the identity is the slot, so the wording in `remove:` is a human-readable selector only — it matches the model's single label edge regardless of the current wording (a reworded edge is still removed):

```yaml
claims:
  - model.punky-willy:
      remove:
        model_relationship:
          - target_machine: rock
          - target_label: several Gottlieb EM models
```

### Export editions and markets

`export_edition_of` is a plain FK field like `variant_of`/`remake_of` — author it as a scalar key whose value is the domestic original's public_id. The destination markets are authored under `export_market:` as a list of explicit-key mappings, like `model_relationship:` but with an **optional** target — at most one of `target_market_location` (a country's public_id; must be a top-level location) or `target_market_label` (plain text for a multi-country region), and an **empty mapping** (`{}`) for a model known to be built for export with an unknown destination:

```yaml
attribution: flipcommons-catalog
claims:
  - model.big-ben-italy:
      export_edition_of: big-ben
      export_market:
        - target_market_location: italy
  - model.phantom-haus:
      export_market:
        - target_market_label: Europe
  - model.dragon:
      export_edition_of: dragoon
      export_market:
        - {}
```

Rules:

- **At most one target key.** `target_market_location` plus `target_market_label` on one member is rejected. Neither is legal — that's the unknown-market row, whose existence alone records "built for export". Write the absent slot by **omitting the key**, not by authoring `null`: an explicit `target_market_label: null` is rejected ("omit the key instead").
- **Locations must be countries.** A non-top-level location (`usa/tx`) is rejected at plan time; a region that isn't a country ("Europe") is a label, not a location.
- **Labels are short plain text.** Non-blank, 120 characters or fewer.
- **A null-location row must be the model's only row** — but on the patch path this is **author discipline, not a validated rule.** Author either country rows, or a single label row, or a single `{}` row — never a mix. Only the editor's planner enforces it; ingest does not, and the DB constraints permit a country row and a null-location row to coexist, so a patch that mixes them applies silently. The same goes across patches: asserting a country market in one patch and `{}` in a later one produces the illegal mix with no error. (One case ingest _does_ catch, confusingly: `{}` and a label row in the **same entry** fold to the same identity and fail as a "duplicate member".)
- **Identity is the location slot.** Re-asserting the label row with different wording rewords it in place (same row, citations intact), like the relationship label edge.

`remove:` names the row by that same identity, as an **explicit-key mapping** — a bare string (`- italy`) is rejected. For the null-location row the identity is the empty slot, so `- {}` removes it, as does a `target_market_label` member with any wording (the current wording doesn't have to match):

```yaml
claims:
  - model.big-ben-italy:
      remove:
        export_market:
          - target_market_location: italy
  - model.dragon:
      remove:
        export_market:
          - {}
```

### Notes & citations

Attach the evidence with `cite:`, and add a `note:` only when there's something the evidence doesn't say for itself:

```yaml
attribution: flipcommons-catalog
claims:
  - model.mazatron:
      cite:
        ref: ipdb:4443 # scheme:identifier — dedups through the seeded IPDB root
        quote: "exists only as a prototype machine" # the evidence; no note needed
      production_status: unreleased
  - model.medieval-madness:
      note: The date is the original run; the 2015 remake is a separate record. # the per-entity "why", beyond the evidence
      cite:
        ref: https://en.wikipedia.org/wiki/Medieval_Madness # raw URL — needs a seeded website root (see Citation sources)
        quote: "was released in 1997"
      production_year: 1997
```

`note:` is the entity's ChangeSet note, shown on its Edit History page. Write it **sparingly** — it's the edit summary, for rationale the citation can't carry: uncertainty, a cleanup or merge explanation, a disambiguation, or why the value follows from what the source states. A **verbatim excerpt does not belong here** — it goes in `quote:` on the `cite:` mapping (below), where the citation already names the source, so the legacy `<source> says "<quote>"` note form is obsolete. A cite carrying a quote usually needs no note at all. See [DataPatchAuthoring.md → `note:`](DataPatchAuthoring.md#note).

`cite:` is external evidence, attached to each of the entry's authored claims and shown beside the field on the edit-history page. Its ref is one of the following forms:

- **`scheme:identifier`** (`ipdb:4443`, `opdb:GRhX5`, `youtube:O-2BXTXLXIY`) — a known scheme. Get-or-creates the source under that scheme's seeded root.
- **`isbn:<isbn>`** (`isbn:9781889933023`) — an **already-seeded authored work**: a book edition, cited by the globally-unique ISBN the record itself carries. `isbn` is not a scheme — a scheme's root mints children from URLs, while a book is its own record — so this form never creates anything: it resolves to the one source holding that ISBN, which is what makes every cite of a work land on the shared record. Hyphens are ignored and an ISBN-10 canonicalizes to its 13-digit form, so both spellings cite the one source; a bad check digit fails the patch. An ISBN nothing is seeded with errors — declare the work in this patch's `sources:` block (processed before claims) or an earlier patch. Cite the **edition**, not the work that groups editions: an ISBN belongs to a specific printing, and an ISBN landing on a record that has editions under it is rejected in favor of the edition's own ISBN.
- **`<root-slug>:<child-slug>`** (`billboard:1945-09-29`, `williams:wpc-95-schematic-manual`, `uspto:us4373731`) — an **already-declared child of a slug-addressed source**: a periodical issue or a publisher's document, cited by its root's authored slug and its own. Like `isbn:`, this form never creates anything — an issue is an editorial record, declared with `slug:`/`parent:` in a `sources:` block (this patch's, processed before claims, or an earlier one); a cite of an undeclared pair fails the patch when it applies. Both segments use the system-wide slug grammar (lowercase, digits, hyphens). A registered scheme key always wins the left segment, so this form can never shadow `ipdb:4443` — and a typo'd scheme key (`ipddb:4443`) parses as this form and fails resolution with a message naming the known schemes.
- **a `http(s)://` URL** (`https://en.wikipedia.org/wiki/...`) — any other web page. The URL's host must fall under a **seeded website root**'s _recognition domain_ — a root's homepage host becomes its recognition domain when the root is declared in a `sources:` block, and a cite on that host **or any subdomain of it** (`static.example.com` under `example.com`) nests here. The cite get-or-creates a `reference` child page under that root, keyed by the exact URL (re-citing reuses it). If no recognition domain matches, the patch errors — declare the website root in this patch's `sources:` block (processed before claims) or an earlier patch. (A root web source is an abstract container, so a patch never mints a parentless one.) A URL matching a known scheme's record pattern (e.g. an `ipdb.org/machine.cgi?id=...` link) is **rejected** — cite it as `scheme:identifier` so it dedups through the scheme path.

`cite:` takes either a bare ref string (as above), or a **mapping** that widens the ref with fields of the minted citation:

```yaml
cite:
  ref: ipdb:4443 # same grammar as the bare string form
  locator: Notes section # optional: where in the source
  quote: "exists only as a prototype machine" # optional: verbatim excerpt
  archive: https://web.archive.org/... # optional: durable snapshot; http(s) refs only
```

`cite:` also takes a **list** of such specs (each element a bare string or a mapping) when a fact is backed by several separate sources — the policy for AI-authored patches is to cite as many facts as possible from multiple separate sources. Every citation in the list attaches to every claim the entry asserts, exactly like a single cite:

```yaml
cite:
  - ipdb:4443
  - ref: https://en.wikipedia.org/wiki/Medieval_Madness
    quote: "was released in 1997"
```

A common pairing is a **proximate source plus the original authority**: an IPDB note that attributes a fact to a book cites both — IPDB with the verbatim quote (that text is in hand) and the book with a page locator and no `quote:` (the book text isn't):

```yaml
cite:
  - ref: ipdb:3905
    quote:
      "According to the Encyclopedia of Pinball Vol 2 page 107, this game is a
      copy of Tura Automatenfabrik Gmbh's 1933 'Tura-Ball'."
  - ref: isbn:9781889933023 # the Encyclopedia volume itself
    locator: Vol. 2, p. 107
```

The same source, locator and quote appearing twice in one list is a hard error — judged on the parsed, normalized spec, so `ref: ipdb:4443` duplicates the bare `ipdb:4443` string form. The same ref with a differing locator or quote is a distinct piece of evidence and fine. An empty list is rejected; omit the key instead.

A `locator:` on a **video** cite (`youtube:<id>`) must be a start time — `95`, `1:35`, `1:02:03` or `1h2m3s` — validated against the video type's timestamp grammar at apply and stored canonical; a malformed one fails the patch loudly. Other types' locators stay freeform.

`quote` is a **verbatim** excerpt: only exact source text and `[...]` ellipses belong in it — a reviewer should be able to follow the citation and ctrl-F find it. Interpretation, translation and rationale go in `note:` instead. Claims in the entry share one citation instance only when the whole citation matches — a differing quote is a distinct piece of evidence even against the same source and locator.

As noted under [File format](#file-format), each `changesets:` item (and each flat entry) is its own ChangeSet, so one record can take **several** corrections in a patch — each with its own `note`/`cite`. Two rules keep that unambiguous:

- **Disjoint fields per record.** The `changesets:` items under one header — and any flat entries — targeting the same record (an existing entity _or_ a same-patch create) must assert/retract **disjoint** `claim_key`s. The same field in two of them — including the same relationship member, or one asserting and another retracting it — is an error. (Each field resolves to one winning claim, so two changesets fighting over it has no coherent meaning.)
- **Provenance must have something to attach to.** A `note`/`cite`/`cites` rides the claims an entry writes, so an entry carrying provenance with nothing to carry it is a hard error — in two shapes. **No carrier** (caught at build): a `cite:`/`note:` on a field-less `create:`, or an empty `tag: []` — there's no authored claim to attach to (a create's own slug/status claims aren't carriers). **No-op diff** (caught at apply): re-asserting a value the source already holds, or a `retract:`/`remove:` of something already gone — the write diffs to nothing, so the provenance would silently vanish. Previously a no-op diff dropped its provenance while reporting success; now it fails loudly. A retract- or remove-only entry is fully valid **when it drops a live claim** — the note rides that deactivation. (The one allowed no-op is an idempotent re-`delete:` of an already-deleted entity. And a field-less create with no provenance is fine — it just creates the entity.)

### Inline citations in descriptions

A markdown field (a `description`) can carry **inline footnotes** — an `[[cite:…]]` marker placed after a fact, backing the nearby sentence, rendered as a numbered `[1]` footnote. Each distinct footnote is one **floating** `CitationInstance` — reached only by its markers, with no `ClaimCitationInstance` join rows: it's evidence for a passage, not for the whole field, so it isn't tied to any one claim. Markers reference that instance by its handle — repeat a handle and both markers point at the one footnote. A marker comes in two forms, told apart by its handle's grammar:

- **A new footnote** uses a **numeric handle** (`[[cite:1]]`) declared in a `cites:` map on the same entry. The handle is an ephemeral authoring label wiring the marker to its source; it is minted to a durable citation at apply time. Handles are arbitrary **all-digit** labels with **no ordering or contiguity** requirement (`1`, `2` is convention, not a rule) and a handle is **not** the rendered footnote number (render numbers by order of first appearance). A handle may repeat — two `[[cite:1]]` markers point at the one footnote.
- **An existing footnote** uses the citation's durable **slug** (`[[cite:bqntvkrs]]`) and needs **no** `cites:` entry — it self-resolves. This is the re-edit form you get from rehydration (below).

First authoring — new citations via numeric handles plus a `cites:` map:

```yaml
attribution: flipcommons-ai-desc-model
claims:
  - model.mazatron:
      description: >
        A 1990 solid-state prototype by Mac Pinball.[[cite:1]]
        Only two units are known to survive.[[cite:2]]
      cites:
        "1": ipdb:4443
        "2": https://pinside.com/thread
      note: "Narrative compiled from IPDB and Pinside."
```

`cites:` declares **only new** citations. Each key is a **numeric handle quoted as a string** (`"1":`, never bare `1:` — an unquoted integer key is a hard parse error) and each value is a cite spec in the **same grammar as `cite:`** — `scheme:identifier`, `isbn:<isbn>`, an `http(s)://` URL or a `{ ref, archive, locator, quote }` mapping. `locator` and `quote` land on the minted footnote instance with the same validation as the entry-level `cite:` (video locators canonicalized, the verbatim-quote rule above applies verbatim):

```yaml
cites:
  "1":
    ref: ipdb:4443
    locator: Notes section
    quote: "exists only as a prototype machine"
```

The spec resolves through the same source get-or-create as `cite:`, so a URL still needs its [website root seeded](#citation-sources).

**Marker ↔ map correspondence is enforced** (a structural error, no DB lookup): every numeric-handle marker must have a `cites:` entry, and every `cites:` key must be a numeric handle referenced by at least one marker. A `cites:` entry keyed by a slug, or one no marker references, is a misuse. A marker that is neither all-digits nor a bare slug — notably a raw `[[cite:id:1]]` (storage form) — is rejected.

**Inline `cites:` count as provenance.** A `description` is a single field, so by the [disjoint-fields rule](#notes--citations) it lives in **one** changeset — you can't split a cited description across two `changesets:` items (or flat entries) on the same record (both would assert the `description` field). Other, disjoint fields on that record may still live in their own items with their own provenance.

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

One limitation to know:

- **A bad or stale slug fails at apply with a _generic_ message** — `"N claim(s) failed validation"`. The specific `Cite not found: [[cite:<slug>]]` only reaches the logs, so don't expect a friendly per-marker error.

### Strict parsing

Duplicate keys error, and values must be JSON-shaped — YAML coercion is off, so a bare `1996-01-01` stays a string and `no` stays `"no"`. A `note:` containing `"` needs YAML quoting (single-quote the value, as in the examples above).

## Citation sources

A patch can create **citation sources** — the reference works (`ipdb`, `pinside`, a manufacturer's site) that `cite:` points at — via a top-level `sources:` block. Unlike claims, a source is _not attributed_ and carries no provenance; `attribution:` still names the source that owns the run's ledger entry, not the citation sources.

```yaml
attribution: flipcommons-catalog # owns the IngestRun; does NOT attribute the sources
sources: # processed before claims, so a cite: below can nest under a root created here
  - name: Wikipedia
    source_type: web # book | periodical | web | video | document
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

Sources sometimes have additional domains **beyond its homepage**. Declare them via `domains:` (a bare public suffix like `co.uk`, or a non-DNS host, is rejected):

```yaml
attribution: flipcommons-catalog
sources:
  - name: Pinball News
    source_type: web
    description: Long-running pinball news site.
    links:
      - {
          url: "https://pinballnews.com/",
          label: Pinball News,
          link_type: homepage,
        }
    domains: # extra recognition hosts beyond the homepage
      - pinballnews.co.uk # a .co.uk alias for the same publication
      - oldpinballnews.com # a former domain, still recognized after a rebrand
      - "https://pinballnews.blogspot.com/" # a secondary home on a platform subdomain (full-URL form is fine)
claims: []
```

A `domains:` entry may also carry a **path**, declaring a path-scoped slice of a **shared multi-tenant CDN host** — the shape for a manufacturer whose documents live only on a host like GoDaddy's `img1.wsimg.com`, where the path segment names the tenant. The path is meaningful: the entry registers the exact `(host, path prefix)` pair, and URLs resolve to the root only when their path sits under the prefix at a segment boundary. Registering such a host **bare is rejected** (it would attribute every tenant's files to one manufacturer), and a path prefix on an ordinary host is rejected too — path scoping exists only for the declared shared hosts (`apps/citation/shared_hosts.py`). Prefixes are case-sensitive and stored verbatim:

```yaml
sources:
  - name: Cardona Pinball Designs
    source_type: web
    links:
      - { url: "https://cardonapinball.com/", link_type: homepage }
    domains:
      # Cardona's tenant directory on GoDaddy's shared CDN — its release-notes
      # PDFs and instruction cards resolve here; other tenants' files do not.
      - img1.wsimg.com/blobby/go/4bd466e8-edb0-49f6-afcc-31250ba5b0f3
claims: []
```

A `sources:` node carries `name`, `source_type`, optional `author`/`publisher`/`year`/`month`/`day`/`date_note`/`isbn`/`description`/`identifier_key`, `domains`, `links` — plus `slug`/`parent` on slug-addressed (periodical, document) nodes, below. Nesting is never expressed by structure — a nested `children` key is rejected. A **web** child is created on demand when you `cite:` a URL on its root's domain; a **periodical** issue or a **document** is declared as its own node whose `parent:` names its root's slug.

**Periodical and document** are the slug-addressed types: neither has a natural identifier (no ISBN, no recognition domain, no scheme key), so their nodes carry an authored `slug` — required, in the system slug grammar, root-unique across all slug-addressed roots and sibling-unique for children. A child node sets `parent:` to its root's slug — an issue to its periodical, a document to its publisher (`williams`, `uspto`) — and the parent must be a root of the child's own type, declared in the same block (any order — parentless nodes are processed first) or an earlier patch. A root slug may not shadow `isbn`, a scheme key or another type's root slug. Archive links (a Google Books scan, an archive.org copy of a manual) hang off the child via `links:`, where every citer benefits:

```yaml
sources:
  - slug: billboard
    name: Billboard
    source_type: periodical
    year: 1894

  - parent: billboard
    slug: 1945-09-29
    name: September 29, 1945
    source_type: periodical
    year: 1945
    month: 9
    day: 29
    links:
      - { url: "https://books.google.com/books?id=…", link_type: archive }
```

A **document** works the same way, with the publisher as the root — its slug is the catalog manufacturer's slug by convention (a naming convention only, never a join key) — and every known copy of the document as typed links:

```yaml
sources:
  - slug: williams
    name: Williams
    source_type: document

  - parent: williams
    slug: wpc-95-schematic-manual
    name: Williams WPC-95 Schematic Manual
    source_type: document
    publisher: Williams
    links:
      - { url: "https://www.ipdb.org/files/…/manual.pdf", link_type: catalog }
      - { url: "https://archive.org/details/…", link_type: archive }
```

Structure-wise this bounds what a patch can cite by `isbn:`. A **standalone** book — one printing, no edition hierarchy — is declarable here with its `isbn:` and citable in the same patch (sources are processed before claims). An **edition under a work** (a volume of a multi-volume set, a revised printing) is a child, so a patch can't declare one; it must already be seeded before a patch cites its ISBN.

The block is **additive get-or-create**: a slug-addressed node is matched by its `(source_type, slug)` (root) or `(parent, slug)` (child) — the slug is the identity within its type, so a renamed periodical is found, not duplicated; every other node is matched by recognition host (homepage ∪ `domains:`), else `isbn`, else `(name, source_type)`. A match is reused — missing links and recognition hosts are backfilled — and an existing row is **never overwritten** (a divergent field warns, doesn't fail). So re-applying is a clean no-op and a patch can't clobber a user-created source or dam later patches. Recognition hosts split across two existing roots skip the node with a warning naming both — resolve the duplicate roots first. A declared issue whose `name` matches an existing sibling under a different slug warns too (two campaigns inventing `1945-09-29` and `sep-29-1945` for one issue) but still creates — a human merges duplicates later.

## Applying patches

Patches don't auto-apply; there's no deploy or startup hook — you run the command manually. Applying patches is the everyday correction path once a database is seeded (production never re-ingests the seed data).

Run `make pull-patches` first to fetch new patch files:

```bash
# Everyday path — applies pending patches from the default dir
# (data/ingest_sources/flippatch/patches/):
make ingest-patches

# That just wraps the management command. Run the mgt cmd directly to point at
# another directory:
cd backend
uv run python manage.py ingest_patches --patches-dir DIR  # override the default dir
```

Patches apply in numeric order. The command **pre-flights the whole batch** (filename format, unique numeric prefixes), then **stops at the first failure** — patches before it stay committed, the failing one and everything after are left unapplied. A missing or empty directory is a no-op. It is idempotent — the ledger skips already-applied patches.

To test-and-revise a patch on localhost before shipping, roll back to a snapshot and re-apply — see [DataPatchAuthoring.md → Validate via snapshot](DataPatchAuthoring.md#validate-via-snapshot).

## The ledger: applied once, immutably

A patch application **is** an ingest run. Each `IngestRun` carries the `patch_id` (filename stem) and an `input_fingerprint` (sha256 of the normalized parsed content — comments, whitespace and key order ignored). The applied set is the `SUCCESS` runs with a `patch_id`, tracked **per database** (what makes "run locally, then on prod" work). On re-run: fingerprint matches → skip (a cosmetic reformat still skips); fingerprint differs → **hard error**, since an applied patch is immutable — a semantic change means you changed history, so add a new numbered patch instead. The invariant is enforced by a partial unique index on `patch_id` where `status='success'`, flipped in the same transaction as the claims.

On localhost, don't fight this guard: roll back to a snapshot and re-apply the revised patch (see [DataPatchAuthoring.md → Validate via snapshot](DataPatchAuthoring.md#validate-via-snapshot)).

## Undoing a patch

There's no automatic revert; source-attributed claims aren't user-revertible. Undo a patch with a **compensating patch** (a later claim supersedes the earlier one).

On localhost, the simplest undo is restoring a pre-apply snapshot (see [DataPatchAuthoring.md → Validate via snapshot](DataPatchAuthoring.md#validate-via-snapshot)) — the compensating-patch rule is for seeded/shared databases whose history can't be rewound.

## Limitations

- **No same-patch reassign-then-delete** — a `delete:`'s referrer check reads live DB state, so a reference reassigned earlier in the _same_ patch isn't yet visible; reassign in an earlier numbered patch, then delete.
- **No forward same-patch references.** A reference — an FK on a `create` or edit, a location `parent`, or a relationship member (`tag`, `location`, …) — resolves against the seed, an earlier patch, or an entry **earlier in this same patch**. What it can't yet do is point _forward_ at an entry declared **below** it: declare the target (manufacturer, title, tag, parent location, …) above its reference, or in an earlier patch. (Citing a `sources:`-declared website root in the same patch always works regardless of order — the source block is processed before claims.)
- **Parent hierarchies stay acyclic.** The self-referential parent relationships (`theme_parent`, `gameplay_feature_parent`) reject a self-link or a cycle, same as the in-app editor. The check is conservative: it weighs the patch's added edges against the current resolved graph and ignores `remove:`, so a patch that both detaches and re-attaches around the same edge may be over-rejected — split it across patches.
