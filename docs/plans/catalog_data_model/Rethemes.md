# Rethemed models

A **re-theme** keeps another machine's gameplay and re-skins it with new art and theme. Right now we have tags for `unofficial-retheme` and `manufacturer-retheme`, but that's lossy; it misses the relationship: what's the model that was rethemed?

Let's represent that as structured data — a new `retheme` `relationship_type` on the `ModelRelationship` edge table. This is the **first new relationship type added since the edge table shipped**, so part of the value here is proving the model-driven scaffolding makes it cheap.

## Decisions

- **New `relationship_type` = `retheme`** on `ModelRelationship` (not dedicated FK columns), because one model — Actros Magic Tour 2013 — is rethemed from **two** donors, which needs two edge rows. See [The data](#the-data).
- **`subordinates = True`.** A re-theme usually gets its own Title, but **not always** — Metallica (Retheme) sits under the Earthshaker Title alongside its donor (1 of the 39 edges) — and where they share a Title the original heads it, never the re-skin (the Big Ben rule). The `(year, name)` tiebreak is not a substitute: a donor is necessarily older than its re-theme, but an undated re-theme would sort ahead of it. (An earlier draft of this plan said `False`, reasoning that a re-theme always gets its own Title; the data disproved it.)
- **`requires_machine_target = True`.** Every re-theme has a known, seeded donor (100% donor knowledge in the data), so a `retheme` edge must carry `target_machine` and never `target_label`. Enforced by a DB CHECK derived from the behavior table, plus a planner row-error for UX.
- **License is a normal, settable axis — no block, no constraint, no `records_license` flag.** A `retheme` edge carries `license_status` exactly like a copy/conversion edge: the editor shows the selector, patches set it, and the read surfaces render it. The patch campaign sets it **case by case** — Shrek (a same-maker re-theme) is `licensed`; the rest stay `unknown` and become `unlicensed` only where a curator can defend it. We never mechanically infer `unlicensed` from a different maker. This captures strictly more than the old binary tag and codifies nothing automatically. See [Verification](#verification).
- **No _data_ migration; the patch session owns tag retirement.** (The feature still ships a _schema_ migration for the two new CHECK constraints — this bullet is only about tag data.) The whole change — edges and tag retirement — is done the same way `conversion-kit` was, mirroring flippatch `0152`–`0154`: `0152` creates the edges, `0153` retracts the tag memberships (`remove: tag: […]` per model), `0154` soft-deletes the tag row. Retraction claims supersede the frozen `0007`/`0008` assertions on both dev and prod — a _data_ migration is unnecessary, and hard-deleting provenance is a deliberate departure we are **not** taking.

## Build scope (this repo)

Two pre-refactors that keep the addition model-driven and DRY, then the type itself as mostly data.

### Pre-refactors

1. **Derive the target-required set from the behavior table** (backend), mirroring the existing `SUBORDINATING_RELATIONSHIP_TYPES` idiom in [model_relationship.py](../../../backend/apps/catalog/models/model_relationship.py). Add `requires_machine_target` to `RelationshipTypeBehavior`, derive `MACHINE_TARGET_REQUIRED_TYPES = tuple(t for t, b in RELATIONSHIP_TYPE_BEHAVIOR.items() if b.requires_machine_target)`, and write the CHECK as `~Q(relationship_type__in=MACHINE_TARGET_REQUIRED_TYPES) | Q(target_machine__isnull=False)`. No `'retheme'` literal anywhere. The existing exhaustiveness test forces every future type to fill both flags (`subordinates`, `requires_machine_target`).
2. **Codegen the per-type behavior to the frontend, and split the editor's blanket `isEdge` gate.** Today `RelatedModelsEditor.svelte` conflates "produces a row" with "allows a label target" under one `isEdge()`; `retheme` breaks that (it's an edge that shows the normal license selector, but is machine-target only — no label). Rather than duplicate the decision frontend-side (a model-driven + DRY violation), export the frontend-relevant flag (`requiresMachineTarget`) from `RELATIONSHIP_TYPE_BEHAVIOR` through codegen — extend `export_entity_meta` or a sibling generated file — and have the editor derive `allowsLabelTarget(kind)` from it. (License shows for every edge kind, so no `showsLicense` split is needed.) A sync test locks the generated subset to the backend table, like the existing `RelationshipTypeLiteral` snapshot test. Future types then get their target rules for free.
3. **Collapse the four parallel phrase maps into one.** `EDGE_LEADS` / `EDGE_NOTES` / `EDGE_INBOUND_HEADINGS` / `EDGE_INBOUND_NOTES` in [relationship-phrase.ts](../../../frontend/src/lib/entities/relationship-phrase.ts) are four `Record<EdgeKind, Record<LicenseStatus, string>>` edited in lockstep per new kind, and they repeat the kind/license key scaffolding four times over. Colocate into one `Record<EdgeKind, Record<LicenseStatus, { lead, note, inboundHeading, inboundNote }>>` so a new kind's phrasing lands in one place and the scaffolding is written once. Same strings, strictly less boilerplate; the accessor functions read the matching field.

### Adding `retheme` (mostly data, compiler-guided)

One enum value auto-propagates to the field choices, DB check-constraint vocabulary, validation schema and export _serialization_ (a retheme edge serializes generically). The rest are echo points a failing test or a TypeScript build error hands you as a checklist — plus two un-guarded export _descriptions_ nothing forces:

- `RETHEME = "retheme", "Re-theme"` in `RelationshipType`.
- `RELATIONSHIP_TYPE_BEHAVIOR[RETHEME]` — `subordinates=False, requires_machine_target=True` (exhaustiveness test forces it).
- `"retheme"` in `RelationshipTypeLiteral` ([schemas.py](../../../backend/apps/catalog/api/schemas.py)) + `make codegen` (snapshot test forces it).
- Migration for the changed `relationship_type__in` CHECK **and** the new derived target-required CHECK.
- Phrase copy for `retheme` — leads, notes, inbound headings, inbound notes for **all three** license statuses, like copy/conversion (patches set license, so `licensed`/`unlicensed` cells are reachable and must render real copy). For re-themes the license axis renders as **official/unofficial** (recovering the old tag vocabulary): `licensed → "Official re-theme of"`, `unlicensed → "Unofficial re-theme of"`, `unknown → "Re-theme of"`; inbound `"Official Re-themes" / "Unofficial Re-themes" / "Re-themes"`. This is display-only — the stored `license_status` stays `licensed`/`unlicensed`, and the editor's license dropdown keeps its generic `Licensed`/`Unlicensed` labels (not changed).
- Editor: `retheme` appears in the kind picker with a machine-target selector and the normal license select, but **no** "Describe it" toggle (machine-target only); switching a row _to_ `retheme` clears any label target (`useLabel=false`).
- `CrossTitleRelation` in [titles.py](../../../backend/apps/catalog/api/titles.py) — a **manual** Literal echo (`remake_of` + the three edge types), **not** derived from `RelationshipTypeLiteral` and not snapshot-guarded, so `retheme` must be added or it fails Pydantic Literal validation on the cross-title link. A re-theme's donor nearly always sits under its own Title (38 of 39 edges), so the cross-title path is a re-theme's normal read, not an edge case. Fix properly: derive it from `RelationshipTypeLiteral` + the remake FK with a guard test, so no future type has to remember.
- Export descriptions in [export.py](../../../backend/apps/catalog/api/export.py) — two **hardcoded, un-guarded** strings that don't auto-propagate. Make them model-driven rather than adding `retheme` by hand: (a) replace the `relationship_type` and `license_status` field descriptions (~lines 178, 180) with a shared `describe_choices(prefix, choices)` helper that joins `RelationshipType.values` / `LicenseStatus.values`, so any future value propagates with zero edits and nothing needs guarding (it's computed); (b) the `model_relationships` shape blurb (~line 343) — reword to non-exhaustive examples so it stops pretending to enumerate: `"Typed relationships like copies and conversions to donor/original machines."` The "like" makes it a sample, not a roster, so a new kind never forces an edit. Net: two echo points become zero.

The `modelEdgeSections` read surface is fully generic over `relationship_type` and needs no per-type code — the donor's page gets an inbound "Re-themes" list for free. The cross-title serializer is generic _except_ for the `CrossTitleRelation` Literal above.

### Tests

New behavioral tests (beyond the exhaustiveness and `RelationshipTypeLiteral` snapshot tests the build already trips):

- **DB CHECK** (`test_db_constraints.py`): a `retheme` edge with `target_label` set / `target_machine` null is rejected by the derived `requires_machine_target` constraint; the same edge with a `target_machine` is accepted. Guard the other kinds still allow a label target.
- **Planner** (`test_api_claims_model_relationships.py`): a `retheme` relationship input carrying `target_label` (no `target_slug`) returns a row-keyed field error, not a 500.
- **Cross-title API** (`test_api_titles.py`): a `retheme` edge whose donor sits under a different Title serializes through the cross-title path — the regression that catches the `CrossTitleRelation` echo — and the donor's model page shows the inbound "Re-themes" section.
- **Codegen sync**: the generated `requiresMachineTarget` subset matches `RELATIONSHIP_TYPE_BEHAVIOR`; and, if `CrossTitleRelation` is derived, a snapshot test that it == `{remake_of}` ∪ `RelationshipTypeLiteral`.
- **Editor DOM** (`RelatedModelsEditor.dom.test.ts`): a `retheme` row shows the license selector and offers **no** "Describe it" toggle; switching an existing label-target row to `retheme` clears the label.
- **Phrase copy** (`relationship-phrase` unit): `retheme` renders "Official re-theme of" / "Unofficial re-theme of" / "Re-theme of" for licensed / unlicensed / unknown.

## Coordination and sequencing

Three actors:

1. **This build (feature):** the pre-refactors and the `retheme` type, on localhost.
2. **Patch session:** rewrite any post-0038 patch that applies the two tags, then reproduce the conversion-kit retirement shape from flippatch `0152`–`0154` — create every `retheme` edge (Actros gets two), retract the tag memberships, soft-delete the two tag rows.
3. **Verification (this build, last):** once the feature is on localhost **and** the edge patches exist, run the swap-and-diff below before shipping.

Order matters only for verification safety: confirm the edges are present (info gained) before the taggings are retired (info removed), so no window loses re-theme knowledge.

## Verification

Before shipping, prove the swap loses no structured donor data and adds more. Apply the edge patches and the tag-retirement patches, then assert:

- Distinct subject models carrying a `retheme` edge == the set formerly tagged.
- Edge count == 39 (38 distinct tagged models; Actros → 2 donor rows).
- Every `retheme` edge has `target_machine` non-null and `target_label = ''` (the `requires_machine_target` guard).
- License is recorded where the campaign judged it defensible — Shrek is `licensed`; the rest are `unknown` unless a curator set `unlicensed`. This is a deliberate re-recording, **not** a blanket carry-over of the old tag: an absent maker means `unknown`, never `unofficial`, and we do not infer `unlicensed` from a different maker. The one thing not reconstructable from edges — the old blanket "unofficial" label — is intentionally dropped (it survives only as retracted provenance history), because it encoded an inference we've decided is unsafe.
- Net gain: structured donor FKs (was free text only), per-edge license set with judgment (richer than the binary tag where known), inbound "Re-themes" lists on donor pages, and the two-donor Actros case as two clean edges. The IPDB donor note in `extra_data` is untouched throughout.

## The data

The following table contains every model tagged `unofficial-retheme` or `manufacturer-retheme` in the local dev database.

- **License words**: whether free text contains any licensing-related word
- **Donor model** (and the donor maker): retrieved from free text

The donor model, the donor's maker and the licensing-word flag are read from the IPDB free text in `extra_data` (`ipdb.notes` / `ipdb.notable_features`); IPDB records the donor with a fixed phrasing — _"This is a re-themed game. It used to be `<Maker>`'s `<year>` '`<Donor>`'."_ An em dash (—) means empty/none.

| Retheme model               | Retheme maker               | Current tag            | License words | Donor model                  | Donor maker  |
| --------------------------- | --------------------------- | ---------------------- | ------------- | ---------------------------- | ------------ |
| Actros Magic Tour 2013      | —                           | `unofficial-retheme`   | —             | Volcano                      | Gottlieb     |
| Actros Magic Tour 2013      | —                           | `unofficial-retheme`   | —             | Mars God of War              | Gottlieb     |
| Alabama Crimson Tide        | —                           | `unofficial-retheme`   | —             | Target Alpha                 | Gottlieb     |
| Aloha                       | —                           | `unofficial-retheme`   | —             | Rainbow                      | Williams     |
| Asterix                     | —                           | `unofficial-retheme`   | —             | Jungle Queen                 | Gottlieb     |
| Big Dick                    | Fabulous Fantasies          | `unofficial-retheme`   | —             | Big Deal                     | Williams     |
| Big Healey                  | —                           | `unofficial-retheme`   | —             | Pat Hand                     | Williams     |
| Boston Red Sox              | —                           | `unofficial-retheme`   | —             | Straight Flush               | Williams     |
| Budapest                    | —                           | `unofficial-retheme`   | —             | Rawhide                      | Stern        |
| Chingy                      | —                           | `unofficial-retheme`   | —             | Black Belt                   | Bally Midway |
| Energie IV                  | —                           | `unofficial-retheme`   | —             | Mariner                      | Bally        |
| Fraggle Rock                | —                           | `unofficial-retheme`   | ✅            | The Flintstones              | Williams     |
| Funtime Frankie             | —                           | `unofficial-retheme`   | —             | The Wiggler                  | Bally        |
| Gas Attack                  | —                           | `unofficial-retheme`   | —             | Breakshot                    | Capcom       |
| Go Girl!                    | —                           | `unofficial-retheme`   | —             | Earthshaker                  | Williams     |
| Grosse Pointe               | —                           | `unofficial-retheme`   | —             | Swords of Fury               | Williams     |
| Iron Maiden                 | —                           | `unofficial-retheme`   | —             | Gorgar                       | Williams     |
| Iron Maiden II              | —                           | `unofficial-retheme`   | —             | F-14 Tomcat                  | Williams     |
| Last Supper                 | —                           | `unofficial-retheme`   | —             | Cabaret                      | Williams     |
| Lucky Luke                  | —                           | `unofficial-retheme`   | —             | Fast Draw                    | Gottlieb     |
| Metallica (Retheme)         | —                           | `unofficial-retheme`   | —             | Earthshaker                  | Williams     |
| Mini Cooper S               | —                           | `unofficial-retheme`   | —             | Grand Prix                   | Williams     |
| Muscle Car Cafe             | Fabulous Fantasies          | `unofficial-retheme`   | —             | Nitro Ground Shaker          | Bally        |
| Naruto                      | —                           | `unofficial-retheme`   | —             | Force II                     | Gottlieb     |
| Night Club                  | —                           | `unofficial-retheme`   | —             | Dogies                       | Bally        |
| Pittsburgh Penguins         | —                           | `unofficial-retheme`   | —             | Dragon                       | Interflip    |
| Queen                       | —                           | `unofficial-retheme`   | —             | Flash Gordon                 | Bally        |
| School Girl Reaper          | —                           | `unofficial-retheme`   | —             | Flip Flop                    | Bally        |
| Sea Nymph                   | —                           | `unofficial-retheme`   | —             | Georgia                      | Williams     |
| Shrek                       | Stern Pinball, Incorporated | `manufacturer-retheme` | ✅            | Family Guy                   | Stern        |
| Slamdunk                    | —                           | `unofficial-retheme`   | —             | Space Invaders               | Bally        |
| Sunset Riders               | —                           | `unofficial-retheme`   | —             | Eight Ball                   | Bally        |
| The French Connection       | —                           | `unofficial-retheme`   | —             | Super Nova                   | Game Plan    |
| The Hellacopters            | —                           | `unofficial-retheme`   | —             | King Pin                     | Gottlieb     |
| Trump's Secret Service      | —                           | `unofficial-retheme`   | —             | Secret Service               | Data East    |
| Udo Lindenberg              | —                           | `unofficial-retheme`   | —             | Harlem Globetrotters On Tour | Bally        |
| Verspiel Dein Wasser nicht! | —                           | `unofficial-retheme`   | —             | Strikes and Spares           | Bally        |
| Wonder Woman                | —                           | `unofficial-retheme`   | —             | Lectronamo                   | Stern        |
| grand theft auto vice city  | —                           | `unofficial-retheme`   | —             | Hollywood Heat               | Premier      |

The two licensing-word hits, verbatim from `ipdb.notes`:

- **Fraggle Rock** (`license`): "…this glass was not made by Bally, nor did Bally seek a license for it." (about the backglass/logo)
- **Shrek** (`licensing`): "…nailing down the licensing of Smash Mouth's 'All Star'…" (about the game's music)

### Recreating / validating

Structured columns (retheme model, retheme maker, tag) and the raw donor-bearing note, straight from the dev SQLite database (`backend/db.sqlite3`):

```sql
SELECT
  m.name                                          AS retheme_model,
  COALESCE(ce.name, '')                           AS retheme_maker,
  t.slug                                          AS current_tag,
  json_extract(m.extra_data, '$."ipdb.notes"')    AS ipdb_notes
FROM catalog_machinemodel m
JOIN catalog_machinemodel_tags mt ON mt.machinemodel_id = m.id
JOIN catalog_tag t                ON t.id = mt.tag_id
LEFT JOIN catalog_corporateentity ce ON ce.id = m.corporate_entity_id
WHERE t.slug IN ('unofficial-retheme', 'manufacturer-retheme')
ORDER BY m.name;
```

Donor model and donor maker are extracted from `ipdb_notes` with the pattern `used to be <Maker>'s <year> '<Donor>'` (note that makers ending in _s_, e.g. Williams, use a bare apostrophe: `Williams' 1948 'Rainbow'`; Actros names two donors; Shrek states its donor in prose — "used the existing Family Guy pinball game design").

Licensing-word scan, restricted to the two free-text fields so metadata keys like `ipdb.image_urls.__license_id` don't produce false positives:

```sql
WITH r AS (
  SELECT m.name,
         lower(
           coalesce(json_extract(m.extra_data, '$."ipdb.notes"'), '') || ' ' ||
           coalesce(json_extract(m.extra_data, '$."ipdb.notable_features"'), '')
         ) AS ftext
  FROM catalog_machinemodel m
  JOIN catalog_machinemodel_tags mt ON mt.machinemodel_id = m.id
  JOIN catalog_tag t                ON t.id = mt.tag_id
  WHERE t.slug IN ('unofficial-retheme', 'manufacturer-retheme')
)
SELECT name FROM r
WHERE ftext LIKE '%licens%' OR ftext LIKE '%licence%' OR ftext LIKE '%official%'
   OR ftext LIKE '%permission%' OR ftext LIKE '%bootleg%'
   OR ftext LIKE '%authoriz%' OR ftext LIKE '%sanction%'
ORDER BY name;
```
