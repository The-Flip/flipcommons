# Pinball model relationships

We've been authoring a series of data patches in sister project Flippatch around relationships between models: bootlegs, licensed copies etc. [Domain Model](../../DomainModel.md) did not support all the model relationships we've been seeing. This is the plan to address it.

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

### Relationship type — a code enum, grown by release

Each edge carries `relationship_type`, a CHECK-constrained enum (`RelationshipType` TextChoices — the state already shipped on this branch). The vocabulary:

- `conversion`: take a physical source machine and use it or components of it. These are complete converted machines, not conversion kits. The target means "built from this donor". Examples:
  - j-martina (patch 0144) = conversions. Header explicitly says "complete converted machines, not conversion kits, so no conversion-kit tag."
- `conversion-kit`: a kit to take a physical machine and convert it to a different machine. The target means "compatible with this donor".
  - Geiger (patch 0142) = conversion kits.
- `copy`: reproduce a design of another machine using new hardware.
- `retheme`: keep another machine's gameplay and re-skin it with new art and theme. Cosmetic-only — same gameplay, new dress — so unlike `copy`/`conversion`/`conversion-kit` it behaves like `variant_of` for collapse and ordering (see [Re-theme](#re-theme)). Two composites over the `license_status` axis: `unofficial-retheme` = `(retheme, unlicensed)`, `manufacturer-retheme` = `(retheme, licensed)`.

Why an enum and not a claims-controlled vocabulary entity (decided 2026-07-15; see [Claims-controlled data, or code?](#claims-controlled-data-or-code) and the [decision record](#vocabulary-entity)): the type set will probably grow — the conversion/conversion-kit distinction emerged mid-campaign, and the `unofficial-retheme`/`manufacturer-retheme` tags are exactly such a growth, now promoted to the `retheme` type ([Re-theme](#re-theme)) — but a **new type is behavior-heavy**: it must decide subordination, variant-collapse re-admission and phrasing across six surfaces. Those decisions belong in code review, not in a contributor's YAML patch.

Adding a type is therefore a release: the enum value, a one-line CHECK-relax migration, phrase-table entries in `relationship-phrase.ts` (the `Record<EdgeKind, …>` types force these at build time) and an explicit subordination/re-admission decision in `first_model_candidates()` / `distinct_machines_q()`. Worth hardening at implementation: those two querysets silently default a new value to not-subordinate/not-readmitted — add an exhaustiveness guard (a per-value classification test) so a new type must decide, the way the phrase tables already force it.

Concept pages, wikilinks and descriptions for the types come later via [Articles](#articles), uniformly with variant, remake and the composites.

### License status — a closed enum

Each edge also carries `license_status`: `licensed` | `unlicensed` | `unknown` (default `unknown` — meaning no source establishes authorization either way). Effectively a boolean plus unknown: the set partitions its space and will not grow ('contested' was considered and rejected above), so it is a CHECK-constrained enum and deliberately not contributor-extensible.

Bootleg, for example, is `(copy, unlicensed)`.

Naming caveat: "license" already means content licensing elsewhere (`Claim.license`, `provenance/licensing.py`). Same word, different concept — fine as an edge-table field name, but don't let API schema names collide.

### Derived concepts: bootleg and licensed-build

Bootleg (`copy` × `unlicensed`) and licensed-build (`copy` × `licensed`) are cross-axis composites. They cannot be values of either axis — an edge carries exactly one type and one status, and making "bootleg" a type would collapse the two orthogonal axes this model deliberately separates. So they have **no first-class representation** in the data model:

- **No filtering by these concepts.** We never shipped a bootleg filter, so it must not have been that important; the goal is dropped. (An interim chips subsystem — a code registry of derived filter concepts plus a `?relationship=` models-list param no frontend ever consumed — was deleted on this branch.) Filtering returns, for composites and simple concepts alike, with [Articles](#articles).
- **Prose links wait for filter pages.** The concept homes — bootleg, licensed-build, conversion kits — arrive with the Page feature. Until then, the 21 `[[tag:...]]` links in unshipped patches (12× bootleg, 1× licensed-build, 8× conversion-kit across 0111/0112/0126/0134 — verified none shipped to prod) are rewritten in step 8 to plain emphasized text, to be re-linked as `[[page:...]]` when Pages land.
- **The 0126 tag descriptions become Page articles.** That prose defines the composites ("a bootleg is…") — exactly Page-shaped content. 0126 is parked until the Page feature exists, then its descriptions seed the bootleg / licensed-build pages, citations intact.
- **Display keeps one composite idiom.** The reader-facing word "bootleg" lives in the phrase tables at the (copy × unlicensed) cells. Accepted direction (2026-07-15, optional to apply): section headings may read composed ("Unlicensed copy of") with bootleg kept as an aka in the note sentences ("This is an unlicensed copy (aka bootleg) of:").

### Re-theme

A **re-theme** keeps another machine's gameplay and re-skins it with new art and theme. The dev DB carries 38 as tags with no lineage FK of any kind — `unofficial-retheme` (37: `metallica-retheme`, `iron-maiden-2`, `naruto`, …) and `manufacturer-retheme` (1: `shrek`) — so the source machine each one re-skins is dropped entirely today, the same information loss [Unrepresentable target info](#unrepresentable-target-info) describes, but total: not one carries `converted_from`/`bootleg_of`/`variant_of` etc. This surfaced as the gap the tag list flagged but the plan had not modeled.

Modeled as one new type over the two axes already present:

- `type: retheme`.
- `unofficial-retheme` = `(retheme, unlicensed)` — an aftermarket reskin by a non-manufacturer (fan, operator, modder); pairs with the `aftermarket` production status.
- `manufacturer-retheme` = `(retheme, licensed)` — an official reskin a manufacturer applied to its own design.

One type, two composites over `license_status` — structurally the [bootleg/licensed-build](#derived-concepts-bootleg-and-licensed-build) pattern over `copy`, so the same display treatment applies (the reader-facing words live in the phrase tables at the retheme cells). **Not two types.**

**Authorship vs authorization (decision).** The two tags actually split on _who did it_ — a non-manufacturer vs the original manufacturer — which only correlates with license. We do **not** add a third first-party/third-party axis: `license_status` carries the distinction well enough, and first-party is derivable — `manufacturer-retheme` is exactly the row whose target machine shares this model's maker. A consequence to note: `retheme` is the one type whose target is routinely the _same_ maker (Shrek re-skinning a Stern design), where every `copy`/`conversion` target is cross-maker.

**Behavior: cosmetic-only, so it collapses like a variant (decision).** Unlike `copy`/`conversion`/`conversion-kit`, a retheme shares the source's gameplay — it differs only in dress, exactly the [variant](../../DomainModel.md#title-model--variants) test. This is the behavior-heavy work [Claims-controlled data, or code?](#claims-controlled-data-or-code) says lives in code review, not a YAML patch. Two decisions the type must make, and both diverge from the copy/conversion defaults — precisely why the [exhaustiveness guard](#relationship-type--a-code-enum-grown-by-release) matters:

- **Subordination — yes.** A retheme never heads its Title; it joins the copy-edge EXISTS test in `first_model_candidates()` / `SUBORDINATE_COPY_FIELDS` so the original design outranks it (the Big Ben rule, extended).
- **Variant-collapse re-admission — like a variant, _not_ like a copy.** A retheme is not a distinct machine for `distinct_machines_q()`; it re-admits from collapse the way a variant does, unlike `copy`/`conversion` which are genuinely distinct builds. This is the one place `retheme` breaks from the copy/conversion behavior, so it must be encoded explicitly rather than inheriting the copy default.

**Target and cardinality.** Single-target in every observed case — you reskin one machine — but it lives in the edge table, not a scalar FK like `variant_of`/`remake_of`, because it carries `license_status` (which a scalar FK can't) and its target may be a `target_label` (an unseeded source) or point across maker and Title. So it does not contradict [Relationships NOT modeled](#relationships-not-modeled): that exclusion is about `variant_of`/`remake_of` being genuinely 1:1 _and_ always-official _and_ collapse-driving scalar FKs; `retheme` needs the status axis and the label rung those two don't have. No multi-target re-theme has been observed; if one ever surfaces the join table already allows it.

**Migration — retheme is prod-shipped, and cannot be a mechanical rewrite.** Correcting the plan's audit: the `unofficial-retheme`/`manufacturer-retheme` vocabulary was born in patch **0007** and all 38 memberships in **0008** — both ≤ 0038, so both shipped to prod (the same kind of pre-0038 prod write the `converted_from` seed was, which [the first audit missed](#migration-map)). But retheme is _not_ the `converted_from` case: `converted_from` carried a target FK, so `catalog/0021` could rewrite it in place; the retheme tags carry **no target at all**, so there is nothing to rewrite into an edge. The retheme edges are therefore **authored per row** — like the [bootleg-tag-without-`bootleg_of`](#why-the-mapping-must-be-applied-per-row-not-mechanically) rows — with the source machine researched by hand for each of the 38 (or a `target_label` where the source is unseeded). This is the bulk of the work and no migration can do it.

What the migration side _does_ own is the prod-shipped 0007/0008 rows: the two tags and their 38 memberships must be retracted. Because this branch is local-only and unshipped, that folds into the **existing** branch migrations rather than adding new ones — extend `catalog/0021`'s sweep (or the step-9 drop migration) to retract the retheme tag memberships in the same pass that handles the other tags, and add the two tags to the step-9 retirement. No new migration file.

`license_status` is per-row, not per-tag: `unofficial-retheme` → `unlicensed` and `manufacturer-retheme` → `licensed` is the honest default (the tags encode authorship, which for rethemes tracks authorization closely), but any row whose sources say otherwise wins — same per-row discipline as [the copy migration](#why-the-mapping-must-be-applied-per-row-not-mechanically).

### Cardinality

A model can have multiple types of relationship. For example, a bootlegger who builds their copy of design G on converted donor cabinets D holds two true facts — (copy, G) and (conversion, D).

We must present the UI in a way that works for both AND'ing and OR'ing (so avoid "a mashup of X+Y" vs "fits X, Y, or Z"), because it's not always clear which it is, as shown below:

#### `conversion`

A model can have multiple `conversion` targets. Examples:

- `playtime-5` (patch 0143): "a conversion of Recel's 1978 'Fair Fight' or maybe Petaco's 'Fair Fight'." That's a conversion with two machine targets whose connective is disjunctive-with-uncertainty — "one of these, we don't know which"
- `robin-hood-4` (patch 0144): "used for their conversion whatever used cabinets they had available." That's a conversion whose donor is disjunctive by nature.
- `the-happy-musketeers`: "a conversion of Hi-Score AND Super Score". Does that mean they converted from one or the other, or both at the same time?
- `summer-time-4`: "a conversion of both Hit-A-Card and Solitaire". Does that mean they converted from one or the other, or both at the same time?

So sometimes those are AND'ed and sometimes OR'ed together.

#### `conversion-kit`

A model can have multiple `conversion-kit` targets. Examples:

- `sky-warrior` = "kit for many SS Gottlieb games"
- `good-year`'s kit "fit three donors"

All the examples we've seen mean it's compatible with multiple donors, thus OR'ed together.

#### `copy`

A `copy` can be a mashup of multiple machines. Examples:

- `punky-willy`: "copy of Premier's Rock and Rock Encore"

All the examples we've seen mean that the inspiration was drawn from all the games, thus AND'ed together.

#### Relationships NOT modeled

Never model relationships whose cardinality is 1:1 in this join table:

- `variant_of`: is never one-to-many; it's always a variant of exactly one Model.
- `remake_of`: is never one-to-many; it's always a remake of exactly one Model.

### Target

The edge's target is one of two representations, exactly one set (XOR):

- `target_machine` (nullable FK): the fully-resolved donor, when we know it and it's seeded.
- `target_label` (text, `""` = absent): plain-text descriptor when the donor isn't seeded ("several Gottlieb EM models", "an unknown 1960s replay game").

A model holds at most **one** label edge. The label's identity is its slot, not its wording (see [Claim identity](#claim-identity)): all of a model's unresolved-target knowledge lives in one row, and rewording it edits that row in place. What this can't represent: two unseeded-target relationships of different types on one model ("copy of an unknown design" + "conversion of whatever cabinets were available") — no observed example, and the escape hatch is the same bounded claim_key rewrite as promoting type into identity.

We considered a third rung — a `target_manufacturer` FK for "a Gottlieb game" — and dropped it: the UX didn't work. When the maker is known but the machine isn't, the maker just lives in the label text, unlinked.

Display:

- Machine target: "Conversion kit for [Galaxie (Gottlieb 1971)]" — the target hyperlinks to the model.
- Label target: "Conversion kit for several Gottlieb EM models" — plain text, no hyperlink (not even on Gottlieb).

### Citations

Each edge row is one claim; citations attach to that claim as a set, like every other relationship claim. When different sources support different aspects of a row — 0150-ltd-do-brasil, where the IPDB citation supports "it's a copy of X" and the Augusto Campos citation supports "unlicensed" — both citations attach to the row, and each citation's quote records which aspect it supports. That's the solution; nothing finer-grained is planned.

Decision record: we considered making the target and `license_status` independently citable and rejected it — it would need a second claim namespace materializing into a column of another namespace's row (a spec shape that doesn't exist) plus citation-targeting editing UI, for no real gain. One consequence to be aware of: actors disagreeing only on `license_status` contest the whole edge claim, same as gameplay `count` today.

### Claim identity

Decision: the edge's claim identity is `target_machine` alone (nullable — `claim_key` already serializes null identity parts). `relationship_type`, `license_status` and `target_label` are all non-identity: a label edge's claim key is constant per model, so the label wording is data _on_ the edge, not the name _of_ it.

Why the label is out of identity: the label is prose and gets copyedited. If the wording were identity, editing a single word would tombstone the edge and mint a new one — the citation history stranded on the dead edge, the edit history reading "removed X, added Y" for what was a correction. Out of identity, a rewording supersedes in place like any other correction, and two actors disagreeing on wording contest one edge instead of materializing two. It also kills the near-duplicate problem structurally: "an unknown Gottlieb game" and "an unidentified Gottlieb" can no longer coexist as two edges.

Consequences: corrections ("actually it's a kit, not a conversion"; "actually the donor was a 2-player") supersede in place and keep the edge's citation history, and disagreements contest one edge instead of materializing two coexisting edges under different claim keys. One edge per (model, machine target) plus at most one label edge per model, enforced with two partial UNIQUE constraints on the through table: `(machine_model, target_machine)` where the machine is set, and `(machine_model)` alone where it is null.

What we give up — both losses sit on the start-restrictive side of the same asymmetry: (a) a model can't hold two relationship types to the same target — no observed counterexample; the real multi-type case (copy of design G + conversion of donor D) has different targets; (b) a model can't hold two label edges (see [Target](#target)). If a counterexample surfaces, promoting type or label wording into identity is a bounded claim_key-rewrite migration, whereas the reverse would mean merging duplicate edges — which is why we start on this side.

### Claims-spec surgery

The edge table must be claims-based (every user-inputted catalog field is), and the existing `ClaimRelationshipSpec` vocabulary can't express it: members cardinality is validated to 1–2, members are single-column FKs, and there's no XOR/nullable identity shape. The target XOR (`target_machine` / `target_label`) needs a new member shape in `apps/provenance/model_bases` — spec vocabulary, validation-schema derivation and resolution projection. The core `Claim` model is untouched: `claim_key` already serializes null identity parts, so identities with holes were anticipated.

**Non-identity member**: with the label out of the claim key ([Claim identity](#claim-identity)), the spec needs one new concept — a field that carries claim data and participates in validation (the XOR, requiredness) but contributes nothing to `claim_key`. `target_label` is its only user: `relationship_type`/`license_status` stay scalar payload (`PayloadField` with `choices`-derived validation — already shipped). (`MemberField.identity` is already optional in the dataclass; the work is in the consumers — claim-key derivation already filters on it, but the resolution reconcile keys rows by the full member tuple and must key by identity parts only.)

Cost of the identity narrowing: prod is untouched (its 0021-materialized edges are all machine-target), but label-edge claims already authored on dev DBs carry the wording in their claim_key and need a one-time claim_key rewrite — or a dev rebuild plus patch replay. Cheap while no edge patch has shipped; strictly more expensive after.

### Claims-controlled data, or code?

A recurring catalog design decision, named once here because this plan lands on both sides of it. The default for any new vocabulary added to the catalog is to make it claims-controlled DB rows (`CreditRole`, `ProductionStatus`, `GameFormat`): rows get descriptions, citations, wikilinks, detail pages and patch-extension without a product release. However, there's a tension:

- **If contributors should be able to extend it, it wants to be claims-controlled.** A new credit role (like maybe "AI ruleset design") is an inert label — a name plus a sort order. Nothing in the system behaves differently because it exists; the worst a bad row can do is be a silly label. Vocabulary like that belongs to the data.
- **If each new value carries behavior that must be modeled in software, it pulls away from claims-control.** For example, adding a new relationship type involves behavior decisions: you must decide whether it subordinates (can it head its Title? — the Big Ben rule), whether it re-admits from variant collapse (is it a distinct machine?), and how it phrases across six display surfaces. Those are catalog-semantics decisions that need code review and ship with the code implementing them; a YAML patch can't carry them safely, and making them patch-authorable hands ordering and collapse behavior to any contributor. While we should seriously consider encoding all those behaviors via the relationship model, we are NOT confident that we've gotten all the behaviors. It's very likely that the next relationship type will require unanticipated new behavioral logic.
- **If the set is closed, it's an enum, full stop.** `licensed | unlicensed | unknown` partitions its space; a fourth value would be a domain change, not a vocabulary extension.

The test for the middle cases: ask what a **new value** would carry. Label only → claims-controlled entity. Behavior → code enum, grown by release. (Caveat for the future: claims-controlled vocabularies are today editable by any contributor — the privileged-edit protection tags and roles want is unbuilt, so every new vocabulary entity also joins that queue.)

## UX

### Editing UX — done

Implemented on this branch (`cf52ccde` edges in detail and edit UX, `31e91e72`/`c1eac348` section-edit harness): the related-models editor at `/models/[SLUG]?edit=related-models` presents one unified "relationship" concept and hides the storage split (`variant_of`/`remake_of` scalar FKs vs `ModelRelationship` edges — deliberate, since variants drive collapse behavior and are genuinely 1:1). The kind picker stays hand-crafted and typed: the enum decision keeps the editor's `satisfies` bindings against the wire Literals as build-time exhaustiveness checks, and a new type added by release extends the picker in the same commit.

Two editor changes the [claim-identity narrowing](#claim-identity) requires: the duplicate-row check keys by target only (kind leaves the key — same target under a different kind is now a correction to one edge, not a second edge), and adding a second describe-it row is blocked (one label edge per model).

### Viewing UX — done

Implemented on this branch (`08eceacf` unified related-model display and legacy-lineage retirement, `196ccc57`/`c886b0d3` detail render path, `ae8323bd` related-title display): machine targets link, label targets render as plain text. There is deliberately no list-filtering UX for relationship concepts (see [Derived concepts](#derived-concepts-bootleg-and-licensed-build)).

## Migration map

**Audit (corrected 2026-07-14).** No patch ≤ 0038 uses `converted_from`, `bootleg_of`, `licensed_build_of` or the three tags — but patches were never the only historical write path: the original **pindata seed ingest** wrote ~53 `converted_from` claims that shipped to prod, which the first audit missed by grepping only patch files. So prod DOES need a data migration for `converted_from`; `bootleg_of`/`licensed_build_of` and the bootleg/licensed-build/conversion-kit tag vocabulary remain prod-clean (born in unshipped 0017/0018/0039). **Second correction (2026-07-15):** the audit above still under-counted the tags — the `retheme` pair is a _third_ prod-shipped write it missed. `unofficial-retheme`/`manufacturer-retheme` and all 38 of their memberships shipped via 0007/0008 (≤ 0038), so their prod rows must be retracted (folded into this branch's existing migrations, which are freely rewritable — the branch is local-only) and the `retheme` edges authored per row ([Re-theme](#re-theme)).

Ordered steps:

1. ~~**Claims-spec surgery**~~ — done (`feat/model-relationships`).
2. ~~**Schema migration + patch authoring syntax**~~ — done (same branch; see [DataPatches.md → Model relationships](../../DataPatches.md#model-relationships)).
3. ~~**Consumer rework**~~ — done: `first_model_candidates()` / `SUBORDINATE_COPY_FIELDS` and the variant collapse dual-read old FKs OR copy/conversion edges.
4. ~~**Retire the old-FK display/API surfaces**~~ — done (2026-07-14, pulled forward from step 6): `converted_from`/`conversions`, `bootleg_of`/`bootlegs` and `licensed_build_of`/`licensed_builds` are no longer serialized in `ModelDetailSchema` or read by the title page's cross-title collector, and the lineage display descriptors are gone. Safe ahead of the patch rework because no shipped patch uses the old fields, so there was nothing to display. The columns remain writable via the claims patch until step 9.
5. ~~**Data migration** (`catalog/0021_lineage_fk_claims_to_edges`)~~ — done: rewrites every remaining legacy-FK claim **in place** into an edge claim (same row, so citations and attribution survive), tag-aware for the conversion-kit mapping, then materializes the edge rows and nulls the legacy columns. Collision rule: where a reworked patch already asserts the same edge from the same actor, the legacy claim transforms but deactivates — the reworked patch's per-row-sourced values win, so nothing is laundered.
6. ~~**Rework the unshipped 0039–0150 patches**~~ — done (separate sessions): every patch authors `model_relationship` edges with per-row-sourced `license_status`; no patch authors the old FKs or tag memberships. (0039 was temporarily restored to author the `bootleg`/`licensed-build` tag rows as wikilink targets; step 8 removes that again — the links become plain text until filter pages provide targets.)
7. **Claim-identity narrowing**: narrow the edge claim identity to `target_machine` alone ([Claim identity](#claim-identity)). Pieces: the non-identity-member spec increment for `target_label` ([Claims-spec surgery](#claims-spec-surgery)); a one-time claim_key rewrite for dev label-edge claims (prod has none — its 0021-materialized edges are all machine-target); the label-rung UNIQUE constraint becomes `(machine_model)` where the machine FK is null; and the two editor changes (duplicate check keys by target only; a second describe-it row is blocked). The enum columns are untouched — the vocabulary-entity conversion was considered and rejected, see the [decision record](#vocabulary-entity).
8. **flippatch rework**: 0039 drops its two tag creates — nothing replaces them; this design has no vocabulary rows. The 21 `[[tag:...]]` wikilinks across 0111/0112/0126/0134 (12× bootleg, 1× licensed-build, 8× conversion-kit) are rewritten to plain emphasized text, to be re-linked as `[[page:...]]` when filter pages land; 0126's composite descriptions are parked until then (they become the bootleg/licensed-build page articles, citations intact). Editing an applied-but-unshipped patch trips the ledger's fingerprint check, so dev DBs rebuild — the standard cost of unshipped-patch rework.
9. **Drop the old columns; retire the tags**: first **re-run the step-5 transform** (import `transform_lineage_claims` from `0021` into the drop migration) to sweep any legacy claims authored since 0021 ran. Then remove `bootleg_of`, `licensed_build_of` and `converted_from` from `MachineModel`, their reverse accessors and remaining write-path surfaces (`_SELF_REF_FIELDS`, the `first_model_candidates()` dual-read, the `NON_DISPLAYED_FORWARD_FKS` exemption in `model-lineage.test.ts`), and retire the tags entirely — the three composite tags plus the two prod-shipped `retheme` tags ([Re-theme](#re-theme)), each row and its authored memberships retracted at the data level (the `conversion-kit` and `retheme` vocabularies are prod-shipped, so their retraction's attribution must outrank the shipped source). The former gate — kit models whose kit-ness lived only in the tag — is closed: `0151-conversion-kits` authors their `conversion_kit` edges (machine targets where sourced, `target_label` for the fits-many kits). Sequencing: the membership sweep must land in an earlier patch than the tag's `delete:` (the delete planner's referrer check reads live DB state), and the retracting patch's attribution must outrank the seed source for the retraction to win resolution.
10. **`make codegen` + remaining derived surfaces.**

Guidance for the patch-rework sessions (the value mapping, per row — not a mechanical migration):

- `bootleg_of` = X → (copy, unlicensed, target_machine=X) — only where `unlicensed` is actually sourced; otherwise `unknown`
- `licensed_build_of` = X → (copy, licensed, target_machine=X)
- `converted_from` = X without `conversion-kit` tag → (conversion, unknown, target_machine=X)
- `converted_from` = X with `conversion-kit` tag → (conversion_kit, unknown, target_machine=X)
- `bootleg` tag without `bootleg_of` → (copy, unlicensed) with the target at whatever resolution the sources support (target_label when unseeded)
- `licensed-build` tag without `licensed_build_of` → (copy, licensed), target likewise
- `conversion-kit` tag without `converted_from` → (conversion_kit, unknown), target likewise
- `unofficial-retheme` tag → (retheme, unlicensed), target researched per row (target_label when unseeded) — see [Re-theme](#re-theme)
- `manufacturer-retheme` tag → (retheme, licensed), target likewise (routinely the same maker)

The retheme rows differ from the others above on two counts (see [Re-theme](#re-theme)): the edges are authored per row because no source FK exists to transform, so every target is hand-sourced; and the prod-shipped 0007/0008 tag memberships must be retracted — folded into the existing branch migrations (this branch is local-only, so `catalog/0021`/the step-9 drop can be rewritten to sweep them), not a new migration.

### Code that keys off the old FKs

- `MachineModel.SUBORDINATE_COPY_FIELDS` / `first_model_candidates()`: the "a copy never heads its Title" ordering rule is keyed to the `bootleg_of`/`licensed_build_of` FKs. It becomes "a copy edge exists" (an EXISTS subquery instead of two null-checks); the Big Ben ordering behavior (Williams original heads the Title, not the Segasa licensed build) must survive the migration.
- The `bootlegs` / `licensed_builds` / `conversions` reverse accessors and everything that reads them (API schemas, related-model view surfaces).

### Why the mapping must be applied per-row, not mechanically

Applying the mapping above mechanically would silently launder unsourced claims, because the old FK names conflated two axes and were used loosely. For example:

- `bootleg_of` → (copy, **unlicensed**) will stamp `unlicensed` onto all 17 Petaco rows, all the RMG rows, and the Maresa set — and we have proved the 'bootleg' status is unsourced. Contrast LTD do Brasil (0150), where `unlicensed` is sourced (Augusto Campos: copying "impunemente", shielded by the Reserva de Mercado). So `bootleg_of` in the wild means sometimes unlicensed-with-evidence (LTD) and sometimes copy-with-no-authorization-source (Petaco/RMG/Maresa).
- `converted_from` → (conversion, **unknown**) is wrong in the other direction: `headsup-pinball` (`wizard-4`/`wizard-3`) is a "licensed conversion kit for Gottlieb's Team One" — a `converted_from` that's demonstrably licensed. Mechanical migration would erase that.

Fortunately, every affected row lives in data patches that have not yet shipped to prod; we've been holding off on applying to prod any data patch since `0038-model-game-formats` because we keep changing the domain model, like this plan is doing right here. So the rework happens in the patch files themselves, per row, with the sources in hand — and nothing mechanical ever runs.

## Rejected alternatives

## Vocabulary-entity

We designed, pressure-tested and rejected (2026-07-15) converting the two enums into claims-controlled vocabulary entities (`ModelRelationshipType`, `ModelRelationshipLicenseStatus`, CreditRole-shaped: patch-authored rows, detail pages, wikilinks, member lists). Rejected because new relationship types are behavior-heavy ([Claims-controlled data, or code?](#claims-controlled-data-or-code)) — patch-authorable behavior columns would hand Title-ordering and variant-collapse decisions to any contributor, the privileged-edit protection that would mitigate that is unbuilt, and the entity route created a two-tier concept-page system (automatic pages for FK-vocabulary concepts, filter pages for variant/remake/composites) that filter pages serve uniformly instead.

Preserved because the conversion is the escape hatch if type growth ever outpaces release cadence. The worked plan, summarized:

- **Sequencing**: expand-contract across three releases, because patch-authored rows can't exist when migrations run (ingest follows migrate; a migration creating the rows itself would collide with the patch's `create:` on the next ingest). Release 1: entities + nullable FK columns beside the enums; post-deploy ingest seeds the vocabulary rows by patch. Release 2: backfill FKs by slug lookup, rewrite edge-claim values (string → vocabulary pk; claim_keys untouched since type/status are non-identity), set NOT NULL, cut code over — with a fail-loud guard ("run `make ingest-patches` first") when edges exist but the vocabulary table is empty, never self-seeding. Release 3: drop the enums, rename the FK columns, delete the Literal bridges.
- **Spec increment**: FK-typed non-identity fields don't exist (`PayloadField` is scalar-only; schema derivation and resolution projection both assert CharField/IntegerField). Needed: pk storage in claim values, slug resolution at ingest and in the edit-API planner, edit-history rendering of names rather than pks, and an unseeded-vocabulary policy (the `EmptyTargetPolicy.SKIP_NAMESPACE` analog for the non-identity path).
- **Behavior columns**: composed display phrasing (type rows carry lead/plural-heading/note templates; status rows an adjective; the bootleg idiom as a display-only aka map in frontend code keyed by slug pair, degrading to plain composition), separate subordination and re-admission flags (complementary sets today, semantically independent), `display_order`, and `is_default`-or-well-known-slug for `unknown`.
- **Wire shape**: input as planner-validated slugs (the `CreditInputSchema.role` precedent); output as nested display-carrying refs so patch-added rows render with zero frontend changes; `CrossTitleRelation` splits into a remake-FK vs edge tagged union; the Literal↔TextChoices snapshot test replaced by unknown-slug rejection tests. The editor's picker becomes two static entries plus the fetched vocabulary.

## Follow-ups

Work that is not in scope for this plan.

### Articles

The general mechanism these relationship concepts need — wikilinkable, described editorial pages over computed (or hardcoded) model sets — is its own feature, specced separately in [Articles.md](Articles.md). Wikilinks would be [[article:italian_bootlegs]]. The `/article/italian_bootlegs` page would have a dynamic list of all models that are unlicensed copies, whose Corporate Entity is from anywhere in Italy.
