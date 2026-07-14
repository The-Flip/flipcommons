# Pinball model relationships

I'm wondering if we should change the domain model to better support the sorts of model relationsihps we've been seeing.

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

Call it something like Derived From? Derivation? Based On? Model Relationships? Conversion kit's aren't really 'derived' from the machines they're related to...

### Type of relationship

Each row would have a `relationship_type` field:

- `conversion`: take a physical source machine and use it or components of it. These are complete converted machines, not conversion kits. The target means "built from this donor". Examples:
  - j-martina (patch 0144) = conversions. Header explicitly says "complete converted machines, not conversion kits, so no conversion-kit tag."
- `conversion_kit`: a kit to take a physical machine and convert it to a different machine. The target means "compatible with this donor".
  - Geiger (patch 0142) = conversion kits.
- `copy`: reproduce a design of another machine using new hardware.

#### Cardinality

I believe a model can only have one type of `relationship_type` - or can we somehow falsify this statement? The project's default posture is to validate strictly because it's easy to relax, hard to tighten. So we will allow only one relationship type until one real-world counterexample emerges.

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

### Target

The edge's target isn't a single FK, but a reference that can sit at any resolution level:

- `target_machine_id` (nullable): the fully-resolved donor, when we know and it's seeded.
- `target_manufacturer_id` (nullable): the Manufacturer (not CorporateEntity), when that's all we know ("a Gottlieb game"). Note that a model is linked to a CorporateEntity, not a Manufacturer, so this is a bit of a weirdness. However, we probably won't know the specific CorporateEntity. Or could we make a good guess?
- `target_label` (nullable text): the free-text descriptor when even the maker is fuzzy ("an unknown 1960s replay game", "many late-70s SS Gottlieb games").

Either `target_machine_id` or one or both of the others must be set. Take `sky-warrior` — "kit for many SS Gottlieb games." The maker is known (Gottlieb, a FK) and there's a qualifiers ("many, SS") so the `target_label` would be "Kit for many SS Gottlieb games".

Frame the three targets as a resolution ladder with an XOR rule: set `target_machine` or (`target_manufacturer` and/or `target_label`), never the machine plus a redundant manufacturer.

### Per-field citations

The edge (target) and the license_status should be independently citable.

This allows us to resolve the "two cites mashed onto one claim" problem, where the IPDB citation supports the fact that it's a copy, and the Augusto-Campos citation supports the fact that it's unlicensed, in data patch 0150-ltd-do-brasil.yaml.

I expect the existing Claims system and data model to support this without changes. LMK if that's not the case. If this requires surgery to Claims, we may be on the wrong track.

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

### Viewing UX

TODO: think through how this changes the viewing surfaces.

## Migration map

TODO: FINISH

- `bootleg_of` → (copy, unlicensed)
- `licensed_build_of` → (copy, licensed)
- `converted_from` without `conversion-kit` → (conversion, unknown licensing)
- `converted_from` + `conversion-kit` → (conversion-kit, unknown licensing)

### Post-migration updates

The (migration)[](#migration-map) will silently launder unsourced claims, because the old FK names conflated two axes and were used loosely. For example:

- `bootleg_of` → (copy, **unlicensed**) will stamp `unlicensed` onto all 17 Petaco rows, all the RMG rows, and the Maresa set — and we have proved the 'bootleg' status is unsourced. Contrast LTD do Brasil (0150), where `unlicensed` is sourced (Augusto Campos: copying "impunemente", shielded by the Reserva de Mercado). So `bootleg_of` in the wild means sometimes unlicensed-with-evidence (LTD) and sometimes copy-with-no-authorization-source (Petaco/RMG/Maresa).
- `converted_from` → (conversion, **unknown**) is wrong in the other direction: `headsup-pinball` (`wizard-4`/`wizard-3`) is a "licensed conversion kit for Gottlieb's Team One" — a `converted_from` that's demonstrably licensed. Mechanical migration would erase that.

Fortunately, all data patches containing `bootleg_of` have not yet shipped to prod; we've been holding off on applying to prod any data patch since `0038-model-game-formats` because we keep changing the domain model, like this plan is doing right here. So after we do the migrations, we'd rework the post 0038 data patches. I _believe_ all silently laundered issues are after that, but we need to check.

#### Migration examples

Real rows from the post-0038 data patches (not yet in prod), showing the target representation and the `license_status` each row's _sources_ actually support, which is not always what a mechanical `bootleg_of → unlicensed` map would produce. Also, some rows that were withheld from data patches because the current model did not support them.

| Patch ID | Models                                                   | `type`         | `license_status` | target                 | why it's here                                                                                                                                                                                                                                                                     |
| -------- | -------------------------------------------------------- | -------------- | ---------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0145     | Petaco ×17 (`drop-a-card-petaco`, `aquarius-petaco`, …)  | copy           | unknown          | machine                | IPDB establishes the copy → target; no source establishes authorization either way. The current model can't express, so it was force-tagged `bootleg`.                                                                                                                            |
| 0140     | Maresa `big-brave`                                       | copy           | unknown          | machine                | IPDB _itself_ says "whether licensed or not is unknown" — here `unknown` is **sourced**, yet the current model forced `bootleg` (= unlicensed).                                                                                                                                   |
| 0150     | LTD do Brasil ×4 (`al-capone`, `zephy`, …)               | copy           | unlicensed       | machine                | IPDB establishes the copy → target; Augusto Campos establishes `license_status`. Two facts, two sources, two fields — the "two cites mashed on one claim" problem.                                                                                                                |
| 0127     | VIFICO ×13                                               | copy           | licensed         | machine                | IPDB "manufactured … under license from Gottlieb/Premier" → `license_status`.                                                                                                                                                                                                     |
| withheld | `the-happy-musketeers`, `summer-time-4`, `mondial-bank`  | conversion     | unknown          | machine ×N             | **Conjunctive** — combined from _all_ donors. Withheld under the current single-FK model.                                                                                                                                                                                         |
| withheld | `playtime-5` (0143 Irmacor)                              | conversion     | unknown          | machine ×2             | "Recel's 1978 'Fair Fight' **or maybe** Petaco's" — two _seeded_ donors, connective disjunctive-uncertain. Rebuts "conversion ⇒ conjunctive".                                                                                                                                     |
| withheld | `good-year`                                              | conversion_kit | unknown          | machine ×N             | **Disjunctive** — one kit, several compatible seeded donors.                                                                                                                                                                                                                      |
| withheld | `punky-willy`                                            | copy           | unknown          | machine ×N             | **Conjunctive** copy-mashup ("a copy of Premier's Rock and Rock Encore").                                                                                                                                                                                                         |
| —        | headsup `wizard-3` / `wizard-4`                          | conversion_kit | licensed         | machine                | "a licensed conversion kit for Gottlieb's Team One" — current model can't pair conversion with a licence.                                                                                                                                                                         |
| 0142     | Geiger                                                   | conversion_kit | unknown          | machine                | Kit ("compatible with") …                                                                                                                                                                                                                                                         |
| 0144     | j-martina                                                | conversion     | unknown          | machine                | … vs. complete conversion ("built from") — the distinction the current tags carry and a bare `type: conversion` would lose.                                                                                                                                                       |
| 0144     | `robin-hood-4` (j-martina)                               | conversion     | unknown          | machine                | Authored single-target, yet the note: Martina "used … whatever used cabinets they had available" — connective disjunctive by nature, and unstated.                                                                                                                                |
| withheld | `sky-warrior`                                            | conversion_kit | unknown          | mfr `gottlieb` + label | **Disjunctive** "kit for many SS Gottlieb games" — fits any of many.                                                                                                                                                                                                              |
| withheld | `wine-grower`                                            | conversion     | unknown          | mfr `gottlieb` + label | "an unknown 1960s-era Gottlieb game."                                                                                                                                                                                                                                             |
| withheld | `star`                                                   | conversion     | unknown          | **label only**         | "conversion of an unidentified 4-player replay game" — even the maker is unknown.                                                                                                                                                                                                 |
| 0148     | RMG ×12 (`galaxie-rmg`, `card-king-rmg`, `only-star`, …) | copy           | unknown          | machine                | An Italian copy of Gottlieb with **no** authorization source either way (unlike LTD, and unlike Spain/Brazil there was no import ban to imply one). Force-tagged `bootleg` today; the mechanical `bootleg_of → unlicensed` map would launder that into an unsourced `unlicensed`. |
| 0148     | RMG `the-best-space-time` (one of the 12)                | copy           | unknown          | machine                | The copied design's target (`space-time-2`) is another _Italian_ maker (Bensa), not a US original — `copy` targets aren't only Gottlieb/Bally/Williams.                                                                                                                           |
| 0148     | RMG `univerx` (one of the 12)                            | copy           | unknown          | machine                | Copy of `galaxie`, but the note _also_ names a second seeded model (`dimension`) — as an **art reference**, not a donor. A "looks multi-target but isn't": not every seeded model a note names is an edge (contrast the genuine conjunctive rows above).                          |

## Alternatives

### Keep current model

Keep the current ways we model relationships. For all the more complicated cases it doesn't handle, simply talk about them in the model's description.

I don't like this because I want to represent the whole web of relationships in the pinball universe. However, because of wikilinks, a description with this information _would_ have _some_ sort of baked-in linkage...
