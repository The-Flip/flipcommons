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

## Patch description

Every patch should contain a top-level description. Don't restate the details of each changeset. Don't reference other patches by number. Examples:

- ❌ NO: Models for the new active makers, one per game. Each model's title (0053) and corporate entity (0051) already exist. Production status reflects each game's real state: Alice Goes to Wonderland is shipping (produced); the rest are announced (a pre-order, an intended launch, a trademark filing). Corporate inception years stay off the entities; these model years carry the makers' timeline. The Wonderland and Pawlowski home machines carry the home-use tag; the already-catalogued Ramp's Road Trip is tagged widebody.
- ✅ YES: Models for the new active makers created in a previous patch.

## Create vocabulary and FK targets in an earlier patch

**Vocabulary must be created by a patch, not added to the seed.** Production is seeded **once** and never re-ingested — it only replays patches. A new taxonomy value (a `GameFormat`, `ProductionStatus`, `Tag`) added only to the pindata seed would never reach prod, and an assignment patch referencing it would fail there. So: create new vocab in an **earlier** patch (its own file, since vocab is usually `flip-museum` while assignments are source-attributed), then reference it.

The same rule covers **any FK target** — a manufacturer, a title, a parent location — because a target is resolved by a live DB lookup and one created earlier in the _same_ patch isn't yet visible (see [DataPatches.md → Limitations](DataPatches.md#limitations)). Create the target in an earlier numbered patch, then point at it.

Those target-creation patches can be **scaffolding-only**: for example, creating Titles before Models, a Franchise before title-franchise links, or Locations before corporate-entity location claims. A scaffolding-only patch may omit per-entry `note:`/`cite:` when it only creates obvious target records and the patch `description:` says why the targets are needed. The later patch that makes the substantive assignment still needs normal evidence.

## Citation sources

A `cite:` to a web URL needs its **website root** seeded first — created in an earlier patch via a top-level `sources:` block (mechanics and the get-or-create policy are in [DataPatches.md → Citation sources](DataPatches.md#citation-sources)). It's another create-in-an-earlier-patch prerequisite, like vocab and FK targets.

Write a root's `description:` to only describe **the source itself** — what it is; do NOT include why this patch cites it:

- ❌ NO: `Company-registration aggregator; used for the registered address of Wonderland Amusements LLC`
- ✅ YES: `Company-registration aggregator`

This is because a root is reusable, so a reason-specific description goes stale the moment the next patch cites the same root for an unrelated fact. Leave per-fact reasoning to the citing entry's `note:`.

## Provenance

The attribution, cite-vs-guard, scaffolding-only exception, and verbatim-note rules are canonical in [DataPatches.md → Authoring a good patch](DataPatches.md#authoring-a-good-patch). Don't restate them — follow them whether you hand-author or generate.

## Writing record descriptions

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

## Validate behind a snapshot

Patches are immutable once applied (per-DB fingerprint), so iterate behind a snapshot — see [DataPatches.md → Iterating on localhost](DataPatches.md#iterating-on-localhost-snapshot-first) for the snapshot/rollback loop and naming. Apply your new, uncommitted patches **from an isolated dir** so the already-applied 0001–N stay untouched:

```bash
cd backend
mkdir -p /tmp/p && cp ../../pindata/patches/00NN-*.yaml /tmp/p/
cp db.sqlite3 db.pre-00NN.sqlite3                      # snapshot (.sqlite3 -> gitignored)
uv run python manage.py ingest_patches --patches-dir /tmp/p
# verify in the running app / Django admin ...
cp db.pre-00NN.sqlite3 db.sqlite3                      # roll back
```

**`--dry-run` is misleading for vocab+assignment pairs.** Dry-run doesn't commit the vocab-creating patch, so the assignment patch reports "FK target does not exist" for every new vocab value. That's an artifact, not a failure — a real apply commits the vocab patch first. Validate with the snapshot+apply above, not dry-run, when one patch creates vocab the next uses.

Then ship: commit + push pindata, publish to R2, and on prod `make pull-ingest && make ingest-patches`.
