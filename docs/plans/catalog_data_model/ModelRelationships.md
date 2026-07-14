# Pinball model relationships

We've been authoring a series of data patches in sister project Flippatch around relationships between models: bootlegs, licensed copies etc. Our current [Domain Model](../../DomainModel.md) does not support all the model relationships we've been seeing. This is the plan to address it.

## Open questions

- **Editing and viewing UX**: Dean is working on these — check in with him as implementation gets close.

## Issues to address

### Unknown licensing status

We aren't sure about the license status of some of these copies. Two different flavors:

- **Unknown**: we don't know the licensing status. For example, RMG is silence (no source either way).
- **Contested**: the licensing status is disputed. Petaco is a contested claim (one blog alleged a licence; we weighed and rejected it → bootleg with a rebuttal note).

Decision: we are NOT going to model 'contested'. That sort of uncertainty could be applied to any scalar claim in the system; there's nothing special about licensing status here; some AI sessions reviewing this doc just happen to currently be in the middle of adjudicating a licensing status dispute. However, we WOULD like to model Petaco as 'unknown'.

### Multiple relationships

We've seen multiple examples of a machine being created / inspired by multiple source machines. Examples:

- `bootleg_of` / `licensed_build_of` (a copy): `punky-willy` (copies both Rock and Rock Encore).
- `converted_from` (a conversion): `the-happy-musketeers` (Hi-Score and Super Score), `summer-time-4` (Hit-A-Card and Solitaire), `mondial-bank`.
- `converted_from` + `conversion-kit` tag: `good-year`'s kit fit three donors; conversion kits often fit "many."

### Conversion licensing status

Conversions also sometimes carry licensing status (headsup-pinball's note literally says "a licensed conversion kit for Gottlieb's Team One").

### Unknown target machine

The target machine isn't always known. This has two sub-issues:

#### Duplicate info

Right now we have a `bootleg` tag because we can't model 'unknown target machine' with `bootleg_of`. But for machines where `bootleg_of` _is_ known, we have to remember to set the tag. We'd prefer a model where we don't have to duplicate info like that.

#### Unrepresentable target info

We have "unknown donor" information that we can't represent by a FK to a specific model:

- `star`: "conversion of an unidentified 4-player replay game"
- `wine-grower`: "an unknown 1960s-era Gottlieb game"
- `sky-warrior`: "kit for many SS Gottlieb games"

It would be nice to be able to record what we _DO_ know, instead of dropping the information entirely. Maybe we could point to a manufacturer via FK when it's known? Would have to be careful to not duplicate the mfr info when we do actually have the FK to a model.

## Solution

Store this information in a join table, so that a single machine can have multiple relationships.

### Join table name

Call it `ModelRelationship`. It matches the existing `?edit=related-models` editor vocabulary.

We considered names like Derived From? Derivation? Based On? However, conversion kits aren't really 'derived' from the machines they're related to.

### Type of relationship

Each row would have a `relationship_type` field:

- `conversion`: take a physical source machine and use it or components of it. These are complete converted machines, not conversion kits. The target means "built from this donor". Examples:
  - j-martina (patch 0144) = conversions. Header explicitly says "complete converted machines, not conversion kits, so no conversion-kit tag."
- `conversion_kit`: a kit to take a physical machine and convert it to a different machine. The target means "compatible with this donor".
  - Geiger (patch 0142) = conversion kits.
- `copy`: reproduce a design of another machine using new hardware.

#### Cardinality

A model can have multiple types of `relationship_type`. For example, a bootlegger who builds their copy of design G on converted donor cabinets D holds two true facts — (copy, G) and (conversion, D).

We must present the UI in a way that works for both AND'ing and OR'ing (so avoid "a mashup of X+Y" vs "fits X, Y, or Z"), because it's not always clear which it is, as shown below:

##### `conversion`

A model can have multiple `conversion` targets. Examples:

- `playtime-5` (patch 0143): "a conversion of Recel's 1978 'Fair Fight' or maybe Petaco's 'Fair Fight'." That's a conversion with two machine targets whose connective is disjunctive-with-uncertainty — "one of these, we don't know which"
- `robin-hood-4` (patch 0144): "used for their conversion whatever used cabinets they had available." That's a conversion whose donor is disjunctive by nature.
- `the-happy-musketeers`: "a conversion of Hi-Score AND Super Score". Does that mean they converted from one or the other, or both at the same time?
- `summer-time-4`: "a conversion of both Hit-A-Card and Solitaire". Does that mean they converted from one or the other, or both at the same time?

So sometimes those are AND'ed and sometimes OR'ed together.

##### `conversion_kit`

A model can have multiple `conversion_kit` targets. Examples:

- `sky-warrior` = "kit for many SS Gottlieb games"
- `good-year`'s kit "fit three donors"

All the examples we've seen mean it's compatible with multiple donors, thus OR'ed together.

##### `copy`

A `copy` can be a mashup of multiple machines. Examples:

- `punky-willy`: "copy of Premier's Rock and Rock Encore"

All the examples we've seen mean that the inspiration was drawn from all the games, thus AND'ed together.

#### Relationships NOT modeled

Never model relationships whose cardinality is 1:1 in this join table:

- `variant_of`: is never one-to-many; it's always a variant of exactly one Model.
- `remake_of`: is never one-to-many; it's always a remake of exactly one Model.

### License status

Each row would have a `license_status` field: `licensed` | `unlicensed` | `unknown` (default).

Bootleg, for example, would be (copy, unlicensed).

Naming caveat: "license" already means content licensing elsewhere (`Claim.license`, `provenance/licensing.py`). Same word, different concept — fine as an edge-table field name, but don't let API schema names collide.

### Target

The edge's target is one of two representations, exactly one set (XOR):

- `target_machine` (nullable FK): the fully-resolved donor, when we know it and it's seeded.
- `target_label` (text, `""` = absent): plain-text descriptor when the donor isn't seeded ("several Gottlieb EM models", "an unknown 1960s replay game").

We considered a third rung — a `target_manufacturer` FK for "a Gottlieb game" — and dropped it: the UX didn't work. When the maker is known but the machine isn't, the maker just lives in the label text, unlinked.

Display:

- Machine target: "Conversion kit for [Galaxie (Gottlieb 1971)]" — the target hyperlinks to the model.
- Label target: "Conversion kit for several Gottlieb EM models" — plain text, no hyperlink (not even on Gottlieb).

### Citations

Each edge row is one claim; citations attach to that claim as a set, like every other relationship claim. When different sources support different aspects of a row — 0150-ltd-do-brasil, where the IPDB citation supports "it's a copy of X" and the Augusto Campos citation supports "unlicensed" — both citations attach to the row, and each citation's quote records which aspect it supports. That's the solution; nothing finer-grained is planned.

Decision record: we considered making the target and `license_status` independently citable and rejected it — it would need a second claim namespace materializing into a column of another namespace's row (a spec shape that doesn't exist) plus citation-targeting editing UI, for no real gain. One consequence to be aware of: actors disagreeing only on `license_status` contest the whole edge claim, same as gameplay `count` today.

### Claim identity

Decision: the edge's claim identity is the target only — the machine-XOR-label pair. `relationship_type` and `license_status` are payload.

Consequences: corrections ("actually it's a kit, not a conversion") supersede in place and keep the edge's citation history, and disagreements contest one edge instead of materializing two coexisting edges under different claim keys. One edge per (model, target), enforced with UNIQUE constraints on the through table (partial, per ladder rung, since the target columns are nullable). What we give up: a model can't hold two relationship types to the same target — no observed counterexample; the real multi-type case (copy of design G + conversion of donor D) has different targets. If a counterexample surfaces, promoting type into identity is a bounded claim_key-rewrite migration, whereas the reverse would mean merging duplicate edges — which is why we start on this side.

### Claims-spec surgery

The edge table must be claims-based (every user-inputted catalog field is), and the existing `ClaimRelationshipSpec` vocabulary can't express it: members cardinality is validated to 1–2, members are single-column FKs, and there's no XOR/nullable identity shape. The target XOR (`target_machine` / `target_label`) needs a new member shape in `apps/provenance/model_bases` — spec vocabulary, validation-schema derivation and resolution projection. The core `Claim` model is untouched: `claim_key` already serializes null identity parts, so multi-part identities with holes were anticipated.

### Rework tags

The [bootleg]/[licensed-build]/[conversion-kit] tags are all representable by "an edge exists" + type + license_status.

In the UI, we still want to continue to filter by these tags. The best UI would be to keep them visually as tags in the UI, so you can filter by clicking the 'bootleg' chip.

We will want to add 'copy' and 'conversion' chips as well.

#### Tag implementation

However we implement it, make it as model-driven as practical.

Options:

- Expose the derived tags through a computed read model (a materialized column or a view the backend keeps in sync). The UI still renders and filters clickable chips; the domain model stays normalized.
- A simple SQL filter. WHERE type='copy' AND license_status='unlicensed' is the bootleg filter. An index likely suffices until proven otherwise. Ship the normalized model; add materialization only if the chip query is slow.

## UX

### Editing UX

The primary editing surface is the related models editors at `/models/[SLUG]?edit=related-models`.

Right now that editor it's a wall of different types of relationships. How about we reduce it to a single Add Relationship button. Click it and it guides you through adding a new relationship. You first select the relationship type (it gives guidance), THEN it gives you the appropriate UI for adding that type - whether it's a scalar field or a M2M.

Note the wizard bridges two storage mechanisms: `variant_of`/`remake_of` stay scalar FKs while copy/conversion/kit edges live in `ModelRelationship`. That split is deliberate (variants drive collapse behavior and are genuinely 1:1), but the editor should present one unified "relationship" concept and hide the storage difference.

### Viewing UX

Dean is working through how this changes the viewing surfaces — check in with him before building.

## Migration map

**Audit result (2026-07-13): there is no data migration.** No patch ≤ 0038 — i.e. nothing that has shipped to prod — uses `converted_from`, `bootleg_of`, `licensed_build_of` or the three tags; even the `bootleg`/`licensed-build` tag vocabulary entries are created in unshipped patch 0039. All 21 patches touching the old fields are 0089–0150, unshipped. Prod needs only DDL; dev DBs are rebuilt by re-ingesting the reworked patches.

Ordered steps:

1. ~~**Claims-spec surgery**~~ — done (`feat/model-relationships`).
2. ~~**Schema migration + patch authoring syntax**~~ — done (same branch; see [DataPatches.md → Model relationships](../../DataPatches.md#model-relationships)).
3. **Consumer rework, BEFORE the patch rework lands**: `first_model_candidates()` / `SUBORDINATE_COPY_FIELDS` derive "subordinate copy" from copy edges, and the bootleg/licensed-build/conversion-kit chips derive from (type, license_status) filters. Old-FK reads keep working until step 6, but once patches stop authoring the old fields, anything still keyed to them silently degrades — hence the ordering.
4. ~~**Retire the old-FK display/API surfaces**~~ — done (2026-07-14, pulled forward from step 6): `converted_from`/`conversions`, `bootleg_of`/`bootlegs` and `licensed_build_of`/`licensed_builds` are no longer serialized in `ModelDetailSchema` or read by the title page's cross-title collector, and the lineage display descriptors are gone. Safe ahead of the patch rework because no shipped patch uses the old fields, so there was nothing to display. The columns remain writable via the claims patch until step 6.
5. **Rework the unshipped 0039–0150 patches** (separate sessions) to author `model_relationship` edges with the `license_status` each row's sources actually support (see [Migration examples](#migration-examples)), and to drop the three tags from the vocabulary patches. Local DBs rebuild by re-ingest; prod is untouched.
6. **Drop the old columns and tags**: remove `bootleg_of`, `licensed_build_of` and `converted_from` from `MachineModel` (pure DDL — prod columns are all NULL), their reverse accessors and remaining write-path surfaces (`_SELF_REF_FIELDS`, the `first_model_candidates()` dual-read, the `NON_DISPLAYED_FORWARD_FKS` exemption in `model-lineage.test.ts`). Sequenced after step 5.
7. **`make codegen` + remaining derived surfaces.**

Guidance for the patch-rework sessions (the value mapping, per row — not a mechanical migration):

- `bootleg_of` = X → (copy, unlicensed, target_machine=X) — only where `unlicensed` is actually sourced; otherwise `unknown`
- `licensed_build_of` = X → (copy, licensed, target_machine=X)
- `converted_from` = X without `conversion-kit` tag → (conversion, unknown, target_machine=X)
- `converted_from` = X with `conversion-kit` tag → (conversion_kit, unknown, target_machine=X)
- `bootleg` tag without `bootleg_of` → (copy, unlicensed) with the target at whatever resolution the sources support (target_label when unseeded)
- `licensed-build` tag without `licensed_build_of` → (copy, licensed), target likewise
- `conversion-kit` tag without `converted_from` → (conversion_kit, unknown), target likewise

### Code that keys off the old FKs

- `MachineModel.SUBORDINATE_COPY_FIELDS` / `first_model_candidates()`: the "a copy never heads its Title" ordering rule is keyed to the `bootleg_of`/`licensed_build_of` FKs. It becomes "a copy edge exists" (an EXISTS subquery instead of two null-checks); the Big Ben ordering behavior (Williams original heads the Title, not the Segasa licensed build) must survive the migration.
- The `bootlegs` / `licensed_builds` / `conversions` reverse accessors and everything that reads them (API schemas, related-model view surfaces).

### Why the mapping must be applied per-row, not mechanically

Applying the mapping above mechanically would silently launder unsourced claims, because the old FK names conflated two axes and were used loosely. For example:

- `bootleg_of` → (copy, **unlicensed**) will stamp `unlicensed` onto all 17 Petaco rows, all the RMG rows, and the Maresa set — and we have proved the 'bootleg' status is unsourced. Contrast LTD do Brasil (0150), where `unlicensed` is sourced (Augusto Campos: copying "impunemente", shielded by the Reserva de Mercado). So `bootleg_of` in the wild means sometimes unlicensed-with-evidence (LTD) and sometimes copy-with-no-authorization-source (Petaco/RMG/Maresa).
- `converted_from` → (conversion, **unknown**) is wrong in the other direction: `headsup-pinball` (`wizard-4`/`wizard-3`) is a "licensed conversion kit for Gottlieb's Team One" — a `converted_from` that's demonstrably licensed. Mechanical migration would erase that.

Fortunately, every affected row lives in data patches that have not yet shipped to prod; we've been holding off on applying to prod any data patch since `0038-model-game-formats` because we keep changing the domain model, like this plan is doing right here. So the rework happens in the patch files themselves, per row, with the sources in hand — and nothing mechanical ever runs.

#### Migration examples

Real rows from the post-0038 data patches (not yet in prod), showing the target representation and the `license_status` each row's _sources_ actually support, which is not always what a mechanical `bootleg_of → unlicensed` map would produce. Also, some rows that were withheld from data patches because the current model did not support them.

| Patch ID | Models                                                   | `type`         | `license_status` | target         | why it's here                                                                                                                                                                                                                                                                     |
| -------- | -------------------------------------------------------- | -------------- | ---------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0145     | Petaco ×17 (`drop-a-card-petaco`, `aquarius-petaco`, …)  | copy           | unknown          | machine        | IPDB establishes the copy → target; no source establishes authorization either way. The current model can't express, so it was force-tagged `bootleg`.                                                                                                                            |
| 0140     | Maresa `big-brave`                                       | copy           | unknown          | machine        | IPDB _itself_ says "whether licensed or not is unknown" — here `unknown` is **sourced**, yet the current model forced `bootleg` (= unlicensed).                                                                                                                                   |
| 0150     | LTD do Brasil ×4 (`al-capone`, `zephy`, …)               | copy           | unlicensed       | machine        | IPDB establishes the copy → target; Augusto Campos establishes `license_status`. Two facts, two sources — both citations attach to the edge row (see [Citations](#citations)).                                                                                                    |
| 0127     | VIFICO ×13                                               | copy           | licensed         | machine        | IPDB "manufactured … under license from Gottlieb/Premier" → `license_status`.                                                                                                                                                                                                     |
| withheld | `the-happy-musketeers`, `summer-time-4`, `mondial-bank`  | conversion     | unknown          | machine ×N     | **Conjunctive** — combined from _all_ donors. Withheld under the current single-FK model.                                                                                                                                                                                         |
| withheld | `playtime-5` (0143 Irmacor)                              | conversion     | unknown          | machine ×2     | "Recel's 1978 'Fair Fight' **or maybe** Petaco's" — two _seeded_ donors, connective disjunctive-uncertain. Rebuts "conversion ⇒ conjunctive".                                                                                                                                     |
| withheld | `good-year`                                              | conversion_kit | unknown          | machine ×N     | **Disjunctive** — one kit, several compatible seeded donors.                                                                                                                                                                                                                      |
| withheld | `punky-willy`                                            | copy           | unknown          | machine ×N     | **Conjunctive** copy-mashup ("a copy of Premier's Rock and Rock Encore").                                                                                                                                                                                                         |
| —        | headsup `wizard-3` / `wizard-4`                          | conversion_kit | licensed         | machine        | "a licensed conversion kit for Gottlieb's Team One" — current model can't pair conversion with a licence.                                                                                                                                                                         |
| 0142     | Geiger                                                   | conversion_kit | unknown          | machine        | Kit ("compatible with") …                                                                                                                                                                                                                                                         |
| 0144     | j-martina                                                | conversion     | unknown          | machine        | … vs. complete conversion ("built from") — the distinction the current tags carry and a bare `type: conversion` would lose.                                                                                                                                                       |
| 0144     | `robin-hood-4` (j-martina)                               | conversion     | unknown          | machine        | Authored single-target, yet the note: Martina "used … whatever used cabinets they had available" — connective disjunctive by nature, and unstated.                                                                                                                                |
| withheld | `sky-warrior`                                            | conversion_kit | unknown          | **label only** | **Disjunctive** "kit for many SS Gottlieb games" — fits any of many.                                                                                                                                                                                                              |
| withheld | `wine-grower`                                            | conversion     | unknown          | **label only** | "an unknown 1960s-era Gottlieb game."                                                                                                                                                                                                                                             |
| withheld | `star`                                                   | conversion     | unknown          | **label only** | "conversion of an unidentified 4-player replay game" — even the maker is unknown.                                                                                                                                                                                                 |
| 0148     | RMG ×12 (`galaxie-rmg`, `card-king-rmg`, `only-star`, …) | copy           | unknown          | machine        | An Italian copy of Gottlieb with **no** authorization source either way (unlike LTD, and unlike Spain/Brazil there was no import ban to imply one). Force-tagged `bootleg` today; the mechanical `bootleg_of → unlicensed` map would launder that into an unsourced `unlicensed`. |
| 0148     | RMG `the-best-space-time` (one of the 12)                | copy           | unknown          | machine        | The copied design's target (`space-time-2`) is another _Italian_ maker (Bensa), not a US original — `copy` targets aren't only Gottlieb/Bally/Williams.                                                                                                                           |
| 0148     | RMG `univerx` (one of the 12)                            | copy           | unknown          | machine        | Copy of `galaxie`, but the note _also_ names a second seeded model (`dimension`) — as an **art reference**, not a donor. A "looks multi-target but isn't": not every seeded model a note names is an edge (contrast the genuine conjunctive rows above).                          |

## Alternatives

### Keep current model

Keep the current ways we model relationships. For all the more complicated cases it doesn't handle, simply talk about them in the model's description.

I don't like this because I want to represent the whole web of relationships in the pinball universe. However, because of wikilinks, a description with this information _would_ have _some_ sort of baked-in linkage...
