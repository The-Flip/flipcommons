# Authoring Data Patches

This doc is the **authoring guidance** for data patches.

For background, [DataPatches.md](DataPatches.md) defines the patch **file format** and how patches are applied.

## Hand-authored or generated?

Two ways to produce a patch's YAML:

- **Hand-author** native YAML against [DataPatches.md](DataPatches.md) when you can get the whole patch right by reading each entry once — a handful of targeted corrections, a record description, a vocab file. This is the default.
- **Generate with `patchkit`** when you're classifying a _population_ from source data: many rows, each needing a live-value `expect:` guard and a verbatim quote extracted-and-escaped from source free text, where hand-copying guards would drift from the live DB and the editorial judgment (what you searched, what you rejected) is worth an auditable worksheet. See [DataPatchKit.md](DataPatchKit.md).

Count is a _symptom_, not the rule — the triggers are repeated mechanical per-row work (pull the live guard, extract the quote, escape it) that a script does more reliably than hand-copying, plus editorial judgment worth recording. A description patch can touch a dozen entities and still be hand-authored: there's no per-row guard or quote extraction to mechanize.

## Schema cheatsheet

Before referencing a field or entity in a patch, confirm it's claimable and learn its `entity_type` string. From `backend/`:

```bash
# Is the field user-inputtable (claimable), and how is it classified?
# Exempt (system) fields: id, uuid, created_at, updated_at, extra_data. Everything
# else concrete on a ClaimControlledModel is a claim. FK -> value is target public_id;
# M2M -> relationship (namespace: [members]); other -> scalar (value as-is).
uv run python manage.py shell -c "from apps.catalog.models import MachineModel; print([f.name for f in MachineModel._meta.get_fields()])"

# entity_type string for a ref (`<entity_type>.<public_id>`):
uv run python manage.py shell -c "from apps.catalog.models.taxonomy import GameFormat; print(GameFormat.entity_type)"
# taxonomy examples: GameFormat -> 'game-format', ProductionStatus -> 'production-status', Tag -> 'tag'
```

## Authoring a good patch

These principles apply whether you hand-author or generate. Each is elaborated in a section below or in [DataPatches.md](DataPatches.md).

### Data patch attribution

**Attribute to `flipcommons-catalog` by default.** It's Flipcommons' own attribution for values we research, scrape and classify ourselves, and it owns the overwhelming majority of patches. Anything web-scraped where we apply editorial judgment is `flipcommons-catalog`; scraping a fact off IPDB or Kineticist does **not** mean attributing the patch to them. Deriving a structured value by classifying a source's free text (parsing IPDB notes into a `game_format`, say) is this same default case, not an exception: `flipcommons-catalog`, with `cite:` to the source text as evidence and `note:` quoting it — there's no source claim to supersede, because the source never had that field.

Reach for a different attribution only in these cases:

- **Retracting or superseding another source's seed-ingest claim** → attribute to _that_ source (`ipdb`, `opdb`, …), so you act on its own claim. This is the only time `ipdb`/`opdb` attribute a patch — never a fresh first-party assertion.
- **Wholesale import of structured data from an external site or API** → create or reuse a source for that site and attribute to it: the site supplies the field directly, so there's no judgment of ours to own.
- **A first-party curatorial source states the fact directly** → that source — `flip-museum` for museum-curated facts no one else claims.
- **AI-generated record descriptions** → the per-entity-type description source `flipcommons-ai-desc-<entity-type>` (see [Record descriptions](#record-descriptions)).

### One entity per entry

**One entity per entry**, carrying all its fields and its single `note`/`cite`.

### Guard every entry

**Guard every entry with `expect:`** against a current resolved value — `year`, or another stable field like `corporate_entity` when year is null — so a typo'd or drifted public_id fails loudly instead of writing to the wrong row. When claims are keyed off an external record (IPDB/OPDB), guard on that id — `expect: { ipdb_id: 4965 }`: it's the most specific guard, it's the same record your `cite:` points at, and it's present even when `year` and `corporate_entity` are both null.

### Note every entry

**Explain every change with `note:`**, written as `<source> says "<verbatim quote>"`. Quote the source _verbatim_ and mark your own omissions with `[...]`. **Preserve the source's own characters**, including non-ASCII letters in foreign-language quotes (e.g. `Günter`, `gegründet`) — notes are stored as UTF-8, so don't strip or transliterate them. Only normalize stray _typography_ that's a copy-paste artifact rather than part of the quote: straighten smart quotes (`“ ”` → `"`) and spell out an ellipsis `…` as `[...]`.

### Cite most entries

**Cite external evidence with `cite:`** — `scheme:identifier` for IPDB/OPDB records, or a raw `http(s)://` URL for any other web page (a forum thread, an archive scan, a manufacturer's page). Reach for the scheme form whenever one exists; the URL form is the escape hatch for sources without a scheme. A URL cite needs its **website root seeded first** (a parentless web source whose homepage link shares the domain) — seed it in an earlier patch, the same vocab-first pattern, then cite pages under it (see [Citation sources](#citation-sources)). Skip the citation when the evidence is in the entity's own data and instead write it in the note such as "Its name contains the word 'prototype'". The cite can also differ from the `expect:` guard: when the evidence lives in a _different_ record's note (a cross-reference — "‹other game› is not a pinball"), guard on the model's own id but `cite:` the record that contains the statement.

**Only assert what a source supports.** If you can't point to evidence, leave the field unset rather than guess: an unset value reads as "unknown", a wrong claim reads as fact.

### Script large patches

**Large curated patches: keep a worksheet, emit from a script.** For a patch spanning dozens of curated rows, record every search you ran (including the ones that found nothing) and the verbatim source text behind each call in a review worksheet, then generate the YAML from a script that reads live field values for the `expect:` guards. Hand-copying guards drifts from the DB; a generator keeps them true and the worksheet keeps the editorial judgment auditable. The dead-end searches matter too — proving a term is absent from the sources is what justifies relying on the signal you did find. **Don't reinvent the generator** — follow [DataPatchKit.md](DataPatchKit.md) and use the shared `patchkit` helper (escaping, `expect:` guards, source-text extraction).

## Patch description

Every patch should contain a top-level description. Don't restate the details of each changeset. Don't reference other patches by number. Examples:

- ❌ NO: Models for the new active makers, one per game. Each model's title (0053) and corporate entity (0051) already exist. Production status reflects each game's real state: Alice Goes to Wonderland is shipping (produced); the rest are announced (a pre-order, an intended launch, a trademark filing). Corporate inception years stay off the entities; these model years carry the makers' timeline. The Wonderland and Pawlowski home machines carry the home-use tag; the already-catalogued Ramp's Road Trip is tagged widebody.
- ✅ YES: Models for the new active makers created in a previous patch.

## Create new vocabulary in a patch, not the seed

**New vocabulary must be created by a patch**, never added to the pindata seed. Production is seeded **once** and never re-ingested — it only replays patches — so a new taxonomy value (`GameFormat`, `ProductionStatus`, `Tag`) added only to the seed would never reach prod, and a patch referencing it would fail there. Create the vocab in a patch, then reference it. The same holds for any new FK target — a manufacturer, a title, a parent location.

Within a file, declare a target **above** the entry that references it (same-patch backward refs resolve). Only a _forward_ reference — pointing at an entry below — still needs an earlier patch (see [DataPatches.md → Limitations](DataPatches.md#limitations)).

Target-creating entries can be **scaffolding** — obvious records like Titles before Models or Locations before corporate-entity claims — and may omit per-entry `note:`/`cite:` when the patch `description:` says why they're needed. The substantive assignment that uses them still needs normal evidence.

## Citation sources

A `cite:` to a web URL needs its **website root** — declared via a top-level `sources:` block (mechanics and the get-or-create policy are in [DataPatches.md → Citation sources](DataPatches.md#citation-sources)). The `sources:` block is processed before claims, so a root declared in the **same** patch is citable in that patch (order-independent), or it can come from an earlier patch.

Write a root's `description:` to only describe **the source itself** — what it is; do NOT include why this patch cites it:

- ❌ NO: `Company-registration aggregator; used for the registered address of Wonderland Amusements LLC`
- ✅ YES: `Company-registration aggregator`

This is because a root is reusable, so a reason-specific description goes stale the moment the next patch cites the same root for an unrelated fact. Leave per-fact reasoning to the citing entry's `note:`.

## Record descriptions

Some patches set narrative record descriptions (Manufacturer, Model, …) — prose, not classified values. The rules:

- **No speculation.** Keep it factual; tell the story, don't guess.
- **Every statement supported.** Back each claim with the entry's `note:`, its `cite:`, or a fact already in the catalog. A statement resting on existing catalog data needs no citation; anything else does.
- **Attribute to the description source.** Each entity type has its own description source named `flipcommons-ai-desc-<entity-type>` — `flipcommons-ai-desc-manufacturer`, `flipcommons-ai-desc-model`, … — not the generic `flipcommons-catalog`. These sources already exist (the seed ingest creates one per entity type), so just reference one — unlike a `cite:` website root, you don't create it in an earlier patch.

### Manufacturer descriptions

- **Don't just list titles.** Naming a debut or signature title is fine; enumerating the catalog is not.
- **Avoid phrasing that dates.** For an ongoing (non-defunct) concern, skip "their latest model", "their one machine" and the like.
- **Give the anchoring facts from the data** — the HQ city, the year founded and (if defunct) the year it stopped making pinball.

## Corporate Entity locations

Corporate entity locations should be a city. Not a country, not a state, not a region. Even if it's hard to find the city, find it. If you can't find a conclusive citation, don't include a citation. We'd rather have an uncited city than no city at all.

## Aliases and abbreviations

Aliases (`manufacturer_alias` and the other `<entity>_alias` namespaces) and `abbreviation` (Title + Model) are relationship members carrying a **bare string**, not a public_id. Author them with the literal registered namespace as the field key and a list of strings:

```yaml
claims:
  - manufacturer.stern:
      manufacturer_alias: [Stern Pinball, Stern Inc, Stern Electronics]
```

- **Case.** Alias values **case-fold** for identity — `Stern` and `stern` are the same alias — but the original case you write is preserved as the display form. Abbreviations are stored **verbatim** (`MM` ≠ `mm`), so write them exactly as they should render.
- **No duplicates within one list.** Two members that fold to the same identity (`[Stern, stern]`, `[MM, MM]`) are rejected — list each distinct value once.
- **Length.** Members are length-checked at build time against the model's column bound (alias 200, abbreviation 50); an over-long member is rejected on `--dry-run`, not silently truncated.
- **Remove** drops a member exactly like an FK member: `remove: { manufacturer_alias: [Stern Inc] }`, attributed to the source holding the membership claim.
- **No `note:` or `cite:` needed.** Aliases and abbreviations don't require `note:`/`cite:`. It fine for them to ride in a Change Set whose `note:`/`cite:` supports other things.

## Validation process

How to validate your changes:

1. [`--dry-run`](#dry-run) is the cheap first pass: it parses the patch and runs every structural check without writing.
2. [Validate via snapshot](#validate-via-snapshot) is the real check: it commits to localhost, so you see the resolved effect in the running app and can validate cross-file dependencies, then roll back.
3. [Hand off to user](#hand-off-to-user) only after those. Committing is the user's call.

### Dry run

`--dry-run` parses the patch and runs every structural check (schema, escaping, `expect:` guards, citation roots) without writing. This catches most single-file mistakes in seconds. However, what it cannot do is show the resolved result or validate a dependency that spans patch files, because it commits nothing.

**`--dry-run` can't validate a reference to an entity from another patch file.** Dry-run commits nothing, so if a later patch references something an earlier patch file creates — a title before its model, a manufacturer, a parent location, a vocab value — the later patch reports "FK target does not exist" for it. When you are testing multiple patch files together where one depends on a previous, validate with the snapshot+apply above instead of dry-run.

### Validate via snapshot

Because a patch is immutable once applied (see [DataPatches.md → The ledger](DataPatches.md#the-ledger-applied-once-immutably)), you can't tweak it and re-run against a DB that already has it. Instead, iterate behind a DB snapshot: copy the SQLite file before applying and restore it to roll back. Name the snapshot after the patch (`db.pre-NNNN.sqlite3`) so it's clear which state it captures; the `.sqlite3` suffix keeps it under the gitignored `*.sqlite3` rule. Apply your new, uncommitted patches **from an isolated dir** so the already-applied 0001–N stay untouched:

```bash
cd backend
mkdir -p /tmp/p && cp ../../pindata/patches/00NN-*.yaml /tmp/p/
cp db.sqlite3 db.pre-00NN.sqlite3                      # snapshot (.sqlite3 -> gitignored)
uv run python manage.py ingest_patches --patches-dir /tmp/p
# verify in the running app / Django admin ...
cp db.pre-00NN.sqlite3 db.sqlite3                      # roll back
```

#### Verify snapshot

After applying, spot-check that the change resolved the way you intended — pull a representative entity and confirm its winning claim carries the right source, value, `cite:` and `note:` (`citation_instances` carries the cite, `changeset.note` the note):

```python
from apps.catalog.models import MachineModel
from apps.provenance.models import Claim
from django.contrib.contenttypes.models import ContentType

ct = ContentType.objects.get_for_model(MachineModel)
c = Claim.objects.filter(
    content_type=ct,
    object_id=MachineModel.objects.get(slug="hyperball").id,
    field_name="game_format",
    is_active=True,
).first()
print(c.source.slug, c.value, [ci.citation_source.identifier for ci in c.citation_instances.all()])
print(c.changeset.note)
```

### Hand off to user

Committing and `make push` in pindata are the user's call — never do either yourself.
