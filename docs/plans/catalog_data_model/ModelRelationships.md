# Pinball model relationships

We've been authoring a series of data patches in sister project Flippatch around relationships between models: bootlegs, licensed copies etc. [Domain Model](../../DomainModel.md) did not support all the model relationships we've been seeing. This is the plan to address it.

## Issues to address

### Unknown licensing status

We aren't sure about the license status of some of these copies. Two different flavors:

- **Unknown**: we don't know the licensing status. For example, RMG is silence (no source either way).
- **Contested**: the licensing status is disputed. Petaco is a contested claim (one blog alleged a licence; we weighed and rejected it → bootleg with a rebuttal note).

Decision: we are NOT going to model 'contested'. That sort of uncertainty could be applied to any scalar claim in the system; there's nothing special about licensing status here; some AI sessions reviewing this doc just happen to currently be in the middle of adjudicating a licensing status dispute. However, we WOULD like to model Petaco as 'unknown'.

### Multiple relationships

We've seen multiple examples of a model being created / inspired by multiple source models. Examples:

- `bootleg_of` / `licensed_build_of` (a copy): `punky-willy` (copies both Rock and Rock Encore).
- `converted_from` (a conversion): `the-happy-musketeers` (Hi-Score and Super Score), `summer-time-4` (Hit-A-Card and Solitaire), `mondial-bank`.
- `converted_from` + `conversion-kit` tag: `good-year`'s kit fit three donors; conversion kits often fit "many."

### Conversion licensing status

Conversions also sometimes carry licensing status (headsup-pinball's note literally says "a licensed conversion kit for Gottlieb's Team One").

### Unknown target model

The target model isn't always known. This has two sub-issues:

#### Duplicate info

Right now we have a `bootleg` tag because we can't model 'unknown target model' with `bootleg_of`. But for models where `bootleg_of` _is_ known, we have to remember to set the tag. We'd prefer a model where we don't have to duplicate info like that.

#### Unrepresentable target info

We have "unknown donor" information that we can't represent by a FK to a specific model:

- `star`: "conversion of an unidentified 4-player replay game"
- `wine-grower`: "an unknown 1960s-era Gottlieb game"
- `sky-warrior`: "kit for many SS Gottlieb games"

It would be nice to be able to record what we _DO_ know, instead of dropping the information entirely. Maybe we could point to a manufacturer via FK when it's known? Would have to be careful to not duplicate the mfr info when we do actually have the FK to a model.

## Solution

Store this information in a join table, so that a single model can have multiple relationships.

### Join table name

Call it `ModelRelationship`. It matches the existing `?edit=related-models` editor vocabulary.

We considered names like Derived From? Derivation? Based On? However, conversion kits aren't really 'derived' from the models they're related to.

### Relationship type — a code enum, grown by release

Each edge carries `relationship_type`, a CHECK-constrained enum (`RelationshipType` TextChoices — the state already shipped on this branch). The vocabulary:

- `conversion`: take a physical source model and use it or components of it. These are complete converted models, not conversion kits. The target means "built from this donor". Examples:
  - j-martina (patch 0144) = conversions. Header explicitly says "complete converted models, not conversion kits, so no conversion-kit tag."
- `conversion-kit`: a kit to take a physical model and convert it to a different model. The target means "compatible with this donor".
  - Geiger (patch 0142) = conversion kits.
- `copy`: reproduce a design of another model using new hardware.

A fourth type, `retheme` (keep another model's gameplay, re-skin the art), is planned as a follow-up in its own branch — see [Rethemes.md](Rethemes.md). It is not part of the shipped enum.

Why an enum and not a claims-controlled vocabulary entity (decided 2026-07-15; see [Claims-controlled data, or code?](#claims-controlled-data-or-code) and the [decision record](#vocabulary-entity)): the type set will probably grow — the conversion/conversion-kit distinction emerged mid-campaign, and the planned `retheme` type ([Rethemes.md](Rethemes.md)) is exactly such a growth — but a **new type is behavior-heavy**: it must decide subordination and phrasing across six surfaces. Those decisions belong in code review, not in a contributor's YAML patch.

Adding a type is therefore a release: the enum value, a one-line CHECK-relax migration, phrase-table entries in `relationship-phrase.ts` (the `Record<EdgeKind, …>` types force these at build time) and an explicit subordination decision in `first_model_candidates()`. Worth hardening at implementation: that queryset silently defaults a new value to not-subordinate — add an exhaustiveness guard (a per-value classification test) so a new type must decide, the way the phrase tables already force it.

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

### Cardinality

A model can have multiple types of relationship. For example, a bootlegger who builds their copy of design G on converted donor cabinets D holds two true facts — (copy, G) and (conversion, D).

We must present the UI in a way that works for both AND'ing and OR'ing (so avoid "a mashup of X+Y" vs "fits X, Y, or Z"), because it's not always clear which it is, as shown below:

#### `conversion`

A model can have multiple `conversion` targets. Examples:

- `playtime-5` (patch 0143): "a conversion of Recel's 1978 'Fair Fight' or maybe Petaco's 'Fair Fight'." That's a conversion with two model targets whose connective is disjunctive-with-uncertainty — "one of these, we don't know which"
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

A `copy` can be a mashup of multiple models. Examples:

- `punky-willy`: "copy of Premier's Rock and Rock Encore"

All the examples we've seen mean that the inspiration was drawn from all the games, thus AND'ed together.

#### Relationships NOT modeled

Never model relationships whose cardinality is 1:1 in this join table:

- `variant_of`: is never one-to-many; it's always a variant of exactly one Model.
- `remake_of`: is never one-to-many; it's always a remake of exactly one Model.

### Target

The edge's target is one of two representations, exactly one set (XOR):

- `target_model` (nullable FK): the fully-resolved donor, when we know it and it's seeded.
- `target_label` (text, `""` = absent): plain-text descriptor when the donor isn't seeded ("several Gottlieb EM models", "an unknown 1960s replay game").

A model holds at most **one** label edge. The label's identity is its slot, not its wording (see [Claim identity](#claim-identity)): all of a model's unresolved-target knowledge lives in one row, and rewording it edits that row in place. What this can't represent: two unseeded-target relationships of different types on one model ("copy of an unknown design" + "conversion of whatever cabinets were available") — no observed example, and the escape hatch is the same bounded claim_key rewrite as promoting type into identity.

We considered a third rung — a `target_manufacturer` FK for "a Gottlieb game" — and dropped it: the UX didn't work. When the manufacturer is known but the model isn't, the manufacturer just lives in the label text, unlinked.

Display:

- Model target: "Conversion kit for [Galaxie (Gottlieb 1971)]" — the target hyperlinks to the model.
- Label target: "Conversion kit for several Gottlieb EM models" — plain text, no hyperlink (not even on Gottlieb).

### Citations

Each edge row is one claim; citations attach to that claim as a set, like every other relationship claim. When different sources support different aspects of a row — 0150-ltd-do-brasil, where the IPDB citation supports "it's a copy of X" and the Augusto Campos citation supports "unlicensed" — both citations attach to the row, and each citation's quote records which aspect it supports. That's the solution; nothing finer-grained is planned.

Decision record: we considered making the target and `license_status` independently citable and rejected it — it would need a second claim namespace materializing into a column of another namespace's row (a spec shape that doesn't exist) plus citation-targeting editing UI, for no real gain. One consequence to be aware of: actors disagreeing only on `license_status` contest the whole edge claim, same as gameplay `count` today.

### Claim identity

Decision: the edge's claim identity is `target_model` alone (nullable — `claim_key` already serializes null identity parts). `relationship_type`, `license_status` and `target_label` are all non-identity: a label edge's claim key is constant per model, so the label wording is data _on_ the edge, not the name _of_ it.

Why the label is out of identity: the label is prose and gets copyedited. If the wording were identity, editing a single word would tombstone the edge and mint a new one — the citation history stranded on the dead edge, the edit history reading "removed X, added Y" for what was a correction. Out of identity, a rewording supersedes in place like any other correction, and two actors disagreeing on wording contest one edge instead of materializing two. It also kills the near-duplicate problem structurally: "an unknown Gottlieb game" and "an unidentified Gottlieb" can no longer coexist as two edges.

Consequences: corrections ("actually it's a kit, not a conversion"; "actually the donor was a 2-player") supersede in place and keep the edge's citation history, and disagreements contest one edge instead of materializing two coexisting edges under different claim keys. One edge per (model, model target) plus at most one label edge per model, enforced with two partial UNIQUE constraints on the through table: `(model, target_model)` where the model is set, and `(model)` alone where it is null.

What we give up — both losses sit on the start-restrictive side of the same asymmetry: (a) a model can't hold two relationship types to the same target — no observed counterexample; the real multi-type case (copy of design G + conversion of donor D) has different targets; (b) a model can't hold two label edges (see [Target](#target)). If a counterexample surfaces, promoting type or label wording into identity is a bounded claim_key-rewrite migration, whereas the reverse would mean merging duplicate edges — which is why we start on this side.

### Claims-spec surgery

The edge table must be claims-based (every user-inputted catalog field is), and the existing `ClaimRelationshipSpec` vocabulary can't express it: members cardinality is validated to 1–2, members are single-column FKs, and there's no XOR/nullable identity shape. The target XOR (`target_model` / `target_label`) needs a new member shape in `apps/provenance/model_bases` — spec vocabulary, validation-schema derivation and resolution projection. The core `Claim` model is untouched: `claim_key` already serializes null identity parts, so identities with holes were anticipated.

**Non-identity member**: with the label out of the claim key ([Claim identity](#claim-identity)), the spec needs one new concept — a field that carries claim data and participates in validation (the XOR, requiredness) but contributes nothing to `claim_key`. `target_label` is its only user: `relationship_type`/`license_status` stay scalar payload (`PayloadField` with `choices`-derived validation — already shipped). (`MemberField.identity` is already optional in the dataclass; the work is in the consumers — claim-key derivation already filters on it, but the resolution reconcile keys rows by the full member tuple and must key by identity parts only.)

Cost of the identity narrowing: prod is untouched (its 0021-materialized edges are all model-target), but label-edge claims already authored on dev DBs carry the wording in their claim_key and need a one-time claim_key rewrite — or a dev rebuild plus patch replay. Cheap while no edge patch has shipped; strictly more expensive after.

### Claims-controlled data, or code?

A recurring catalog design decision, named once here because this plan lands on both sides of it. The default for any new vocabulary added to the catalog is to make it claims-controlled DB rows (`CreditRole`, `ProductionStatus`, `GameFormat`): rows get descriptions, citations, wikilinks, detail pages and patch-extension without a product release. However, there's a tension:

- **If contributors should be able to extend it, it wants to be claims-controlled.** A new credit role (like maybe "AI ruleset design") is an inert label — a name plus a sort order. Nothing in the system behaves differently because it exists; the worst a bad row can do is be a silly label. Vocabulary like that belongs to the data.
- **If each new value carries behavior that must be modeled in software, it pulls away from claims-control.** For example, adding a new relationship type involves behavior decisions: you must decide whether it subordinates (can it head its Title? — the Big Ben rule) and how it phrases across six display surfaces. Those are catalog-semantics decisions that need code review and ship with the code implementing them; a YAML patch can't carry them safely, and making them patch-authorable hands ordering behavior to any contributor. While we should seriously consider encoding all those behaviors via the relationship model, we are NOT confident that we've gotten all the behaviors. It's very likely that the next relationship type will require unanticipated new behavioral logic.
- **If the set is closed, it's an enum, full stop.** `licensed | unlicensed | unknown` partitions its space; a fourth value would be a domain change, not a vocabulary extension.

The test for the middle cases: ask what a **new value** would carry. Label only → claims-controlled entity. Behavior → code enum, grown by release. (Caveat for the future: claims-controlled vocabularies are today editable by any contributor — the privileged-edit protection tags and roles want is unbuilt, so every new vocabulary entity also joins that queue.)

## UX

### Editing UX

Implemented on this branch (`cf52ccde` edges in detail and edit UX, `31e91e72`/`c1eac348` section-edit harness): the related-models editor at `/models/[SLUG]?edit=related-models` presents one unified "relationship" concept and hides the storage split (`variant_of`/`remake_of` scalar FKs vs `ModelRelationship` edges — deliberate, since variants drive collapse behavior and are genuinely 1:1). The kind picker stays hand-crafted and typed: the enum decision keeps the editor's `satisfies` bindings against the wire Literals as build-time exhaustiveness checks, and a new type added by release extends the picker in the same commit.

Two editor changes the [claim-identity narrowing](#claim-identity) requires: the duplicate-row check keys by target only (kind leaves the key — same target under a different kind is now a correction to one edge, not a second edge), and adding a second describe-it row is blocked (one label edge per model).

### Viewing UX

Implemented on this branch (`08eceacf` unified related-model display and legacy-lineage retirement, `196ccc57`/`c886b0d3` detail render path, `ae8323bd` related-title display): model targets link, label targets render as plain text. There is deliberately no list-filtering UX for relationship concepts (see [Derived concepts](#derived-concepts-bootleg-and-licensed-build)).

## Migration map

**Audit (2026-07-14; corrected 2026-07-16).** No patch ≤ 0038 uses `converted_from`, `bootleg_of`, `licensed_build_of` or the three tags. However, the original **pindata seed ingest** wrote ~53 `converted_from` claims that shipped to prod, which the first audit missed by grepping only patch files. So prod DOES need a data migration for `converted_from`; `bootleg_of`/`licensed_build_of` and the bootleg/licensed-build tag vocabulary remain prod-clean (born in unshipped patches). **Third correction (2026-07-16, found during step 9):** the `conversion-kit` tag is NOT prod-clean — the seed ingest wrote the tag row (flipcommons-catalog-attributed) and 66 opdb-attributed memberships, the same missed-write class as the `converted_from` claims. Its retirement is therefore data-level: an opdb-attributed membership sweep (a `remove:` supersedes only the holding source's claim) followed by a flipcommons-catalog `delete:` of the tag row (patches 0153/0154).

Another prod-shipped write sits outside this PR's scope: the `retheme` tags. These will be retracted in [Rethemes.md](Rethemes.md).

## Shipping plan

This work ships as multiple independent PRs, each retiring only the columns and tags for which it is responsible:

- **Model Relationships** (this doc): the `copy`/`conversion`/`conversion-kit` edge table and everything in [Sequencing](#sequencing) below.
- **Rethemes** ([Rethemes.md](Rethemes.md)): adds a `retheme` `ModelRelationship` relationship type; retracts the prod-shipped `retheme` tags.
- **Exports** ([Exports.md](Exports.md)): adds `export_edition_of` and an export-market join table; deletes the dead `export` tag.

### Rework but don't ship the data patches

Before shipping each PR, garden whatever post-0038 patches that branch's changes touch, to vet the work — but hold off shipping the patches. None of the post-0038 data patches will ship with any of the above PRs. Once all the Flipcommons PRs have shipped, we will continue adding new data patches for a little while, since most new data patches have been a rich source of "we should really change the domain model before we ship those previous data patches" and I don't think we're done with that yet. The quality of the older patches has increased by holding them (improved citation mechanics, finer distinctions on relationships etc). As soon as we see stabilization where new patches aren't calling for domain model changes, we'll ship all the post-0038 data patches.

## Sequencing

Sequencing of this PR.

1. ✅ DONE: **Claims-spec surgery** — done on same branch, `feat/model-relationships`.
2. ✅ DONE: **Schema migration + patch authoring syntax** — done on same branch; see [DataPatches.md → Model relationships](../../DataPatches.md#model-relationships).
3. ✅ DONE: **Consumer rework** — done on same branch: `first_model_candidates()` / `SUBORDINATE_COPY_FIELDS` dual-read old copy FKs OR copy edges.
4. ✅ DONE: **Retire the old-FK display/API surfaces** — done on same branch: `converted_from`/`conversions`, `bootleg_of`/`bootlegs` and `licensed_build_of`/`licensed_builds` are no longer serialized in `ModelDetailSchema` or read by the title page's cross-title collector, and the lineage display descriptors are gone. The 53 seed-derived `converted_from` claims temporarily lose that display path within the branch until step 5 materializes their replacement edges; these steps must therefore ship together. The columns remain writable via the claims patch until step 9.
5. ✅ DONE: **Data migration** (`catalog/0021_lineage_fk_claims_to_edges`) — done on same branch: rewrites every remaining legacy-FK claim **in place** into an edge claim (same row, so citations and attribution survive), tag-aware for the conversion-kit mapping, then materializes the edge rows and nulls the legacy columns. Collision rule: where a reworked patch already asserts the same edge from the same actor, the legacy claim transforms but deactivates — the reworked patch's per-row-sourced values win, so nothing is laundered.
6. ✅ DONE: **Rework the unshipped 0039–0150 patches** — done on same branch: every patch authors `model_relationship` edges with per-row-sourced `license_status`; no patch authors the old FKs or tag memberships. (0039 was temporarily restored to author the `bootleg`/`licensed-build` tag rows as wikilink targets; step 8 removes that again — the links become plain text until filter pages provide targets.)
7. ✅ DONE: **Claim-identity narrowing** — done on same branch; the worked plan is [ClaimIdentityNarrowing.md](ClaimIdentityNarrowing.md): the edge claim identity is `target_model` alone, `target_label` is a non-identity member (the lossless members/payload schema split landed first as its own commit), the label-rung UNIQUE is `(machine_model)` where the model FK is null, dev was rebuilt rather than key-rewritten (verified: 53 prod claims transform through `0021` with narrowed keys; exactly 24 label edges across 24 models match the authored patches; ingest and resolve converge), and both editor changes shipped. The [exhaustiveness guards](#relationship-type--a-code-enum-grown-by-release) also landed: `RELATIONSHIP_TYPE_BEHAVIOR` drives `first_model_candidates()` with a per-value classification test, and the editor's kind picker is backed by a `Record<RelationshipKind, …>`.
8. ✅ DONE: **flippatch rework**: 0039 drops its two tag creates — nothing replaces them; this design has no vocabulary rows. The 21 `[[tag:...]]` wikilinks across 0111/0112/0126/0134 (12× bootleg, 1× licensed-build, 8× conversion-kit) are rewritten to plain emphasized text, to be re-linked as `[[page:...]]` when filter pages land; 0126's composite descriptions are parked until then (they become the bootleg/licensed-build page articles, citations intact). Editing an applied-but-unshipped patch trips the ledger's fingerprint check, so dev DBs rebuild — the standard cost of unshipped-patch rework.
9. ✅ DONE: **Drop the old columns; retire the composite tags** — done on same branch: `catalog/0022` re-runs the `0021` transform as a final sweep then drops the three columns; the model, `_SELF_REF_FIELDS`, the `first_model_candidates()` dual-read and the frontend `NON_DISPLAYED_FORWARD_FKS` exemption are gone; `bootleg`/`licensed-build` needed no data work because their creates were removed in step 8; `conversion-kit` proved seed-shipped (see the corrected audit) and is retired by patches 0153 (opdb membership sweep) + 0154 (tag `delete:`); verified by a full rebuild — pre-0039 snapshot → migrate through 0022 → replay 151 patches → tag `status=deleted`, zero memberships, 24 label edges intact, ingest and resolve converge. A model targeted by another active model's edge **blocks** soft delete via the `inbound_relationship_sources` usage blocker (the edge row has no lifecycle, so the walk hops through it to the owning source model — the Tag member-models channel) — preserving the referential rule the `converted_from` FK used to enforce; a soft-deleted source releases the block. Pinned by test both ways. Original scope: first **re-run the step-5 transform** (import `transform_lineage_claims` from `0021` into the drop migration) to sweep any legacy claims authored since 0021 ran. Then remove `bootleg_of`, `licensed_build_of` and `converted_from` from `MachineModel`, their reverse accessors and remaining write-path surfaces (`_SELF_REF_FIELDS`, the `first_model_candidates()` dual-read, the `NON_DISPLAYED_FORWARD_FKS` exemption in `model-lineage.test.ts`), and retire the three composite tags (`bootleg`/`licensed-build`/`conversion-kit`) — each row and its authored memberships retracted at the data level; where a composite tag proves prod-shipped (see the audit above), its retraction's attribution must outrank the shipped source. The former gate — kit models whose kit-ness lived only in the tag — is closed: `0151-conversion-kits` authors their `conversion_kit` edges (model targets where sourced, `target_label` for the fits-many kits). Sequencing: the membership sweep must land in an earlier patch than the tag's `delete:` (the delete planner's referrer check reads live DB state). The `retheme` tags are **not** retired here — they belong to the Retheme PR ([Rethemes.md](Rethemes.md)); the dead `export` tag to the Export PR ([Exports.md](Exports.md)). Each PR retires only the tags and columns it is responsible for.
10. ✅ DONE: **`make codegen` + remaining derived surfaces** — folded into step 9: `entity-meta.ts` no longer carries the three FKs and the lineage test needs no exemption list.

Guidance for the patch-rework sessions (the value mapping, per row — not a mechanical migration):

- `bootleg_of` = X → (copy, unlicensed, target_machine=X) — only where `unlicensed` is actually sourced; otherwise `unknown`
- `licensed_build_of` = X → (copy, licensed, target_machine=X)
- `converted_from` = X without `conversion-kit` tag → (conversion, unknown, target_machine=X)
- `converted_from` = X with `conversion-kit` tag → (conversion_kit, unknown, target_machine=X)
- `bootleg` tag without `bootleg_of` → (copy, unlicensed) with the target at whatever resolution the sources support (target_label when unseeded)
- `licensed-build` tag without `licensed_build_of` → (copy, licensed), target likewise
- `conversion-kit` tag without `converted_from` → (conversion_kit, unknown), target likewise

The `retheme` tags (`unofficial-retheme`/`manufacturer-retheme`) are handled separately in [Rethemes.md](Rethemes.md), not by this PR.

### Code that keys off the old FKs

- `MachineModel.SUBORDINATE_COPY_FIELDS` / `first_model_candidates()`: the "a copy never heads its Title" ordering rule is keyed to the `bootleg_of`/`licensed_build_of` FKs. It becomes "a copy edge exists" (an EXISTS subquery instead of two null-checks); the Big Ben ordering behavior (Williams original heads the Title, not the Segasa licensed build) must survive the migration.
- The `bootlegs` / `licensed_builds` / `conversions` reverse accessors and everything that reads them (API schemas, related-model view surfaces).

### Why the mapping must be applied per-row, not mechanically

Applying the mapping above mechanically would silently launder unsourced claims, because the old FK names conflated two axes and were used loosely. For example:

- `bootleg_of` → (copy, **unlicensed**) will stamp `unlicensed` onto all 17 Petaco rows, all the RMG rows, and the Maresa set — and we have proved the 'bootleg' status is unsourced. Contrast LTD do Brasil (0150), where `unlicensed` is sourced (Augusto Campos: copying "impunemente", shielded by the Reserva de Mercado). So `bootleg_of` in the wild means sometimes unlicensed-with-evidence (LTD) and sometimes copy-with-no-authorization-source (Petaco/RMG/Maresa).
- `converted_from` → (conversion, **unknown**) is wrong in the other direction: `headsup-pinball` (`wizard-4`/`wizard-3`) is a "licensed conversion kit for Gottlieb's Team One" — a `converted_from` that's demonstrably licensed. Mechanical migration would erase that.

The rows whose relationship type or licensing status required source-by-source judgment live in unshipped post-0038 patches, so those patch files were reworked with the evidence in hand. Production's 53 seeded `converted_from` claims were handled separately by the data migration described above, and the seeded `conversion-kit` memberships were retired by patches 0153 and 0154. The evidence-sensitive classifications were therefore never applied mechanically, while the already-shipped legacy state still received an explicit migration path.

## Rejected alternatives

## Vocabulary-entity

We designed, pressure-tested and rejected (2026-07-15) converting the two enums into claims-controlled vocabulary entities (`ModelRelationshipType`, `ModelRelationshipLicenseStatus`, CreditRole-shaped: patch-authored rows, detail pages, wikilinks, member lists). Rejected because new relationship types are behavior-heavy ([Claims-controlled data, or code?](#claims-controlled-data-or-code)) — patch-authorable behavior columns would hand Title-ordering decisions to any contributor, the privileged-edit protection that would mitigate that is unbuilt, and the entity route created a two-tier concept-page system (automatic pages for FK-vocabulary concepts, filter pages for variant/remake/composites) that filter pages serve uniformly instead.

Preserved because the conversion is the escape hatch if type growth ever outpaces release cadence. The worked plan, summarized:

- **Sequencing**: expand-contract across three releases, because patch-authored rows can't exist when migrations run (ingest follows migrate; a migration creating the rows itself would collide with the patch's `create:` on the next ingest). Release 1: entities + nullable FK columns beside the enums; post-deploy ingest seeds the vocabulary rows by patch. Release 2: backfill FKs by slug lookup, rewrite edge-claim values (string → vocabulary pk; claim_keys untouched since type/status are non-identity), set NOT NULL, cut code over — with a fail-loud guard ("run `make ingest-patches` first") when edges exist but the vocabulary table is empty, never self-seeding. Release 3: drop the enums, rename the FK columns, delete the Literal bridges.
- **Spec increment**: FK-typed non-identity fields don't exist (`PayloadField` is scalar-only; schema derivation and resolution projection both assert CharField/IntegerField). Needed: pk storage in claim values, slug resolution at ingest and in the edit-API planner, edit-history rendering of names rather than pks, and an unseeded-vocabulary policy (the `EmptyTargetPolicy.SKIP_NAMESPACE` analog for the non-identity path).
- **Behavior columns**: composed display phrasing (type rows carry lead/plural-heading/note templates; status rows an adjective; the bootleg idiom as a display-only aka map in frontend code keyed by slug pair, degrading to plain composition), a subordination flag, `display_order`, and `is_default`-or-well-known-slug for `unknown`.
- **Wire shape**: input as planner-validated slugs (the `CreditInputSchema.role` precedent); output as nested display-carrying refs so patch-added rows render with zero frontend changes; `CrossTitleRelation` splits into a remake-FK vs edge tagged union; the Literal↔TextChoices snapshot test replaced by unknown-slug rejection tests. The editor's picker becomes two static entries plus the fetched vocabulary.

## Follow-ups

Work that is not in scope for this plan.

### Articles

The general mechanism these relationship concepts need — wikilinkable, described editorial pages over computed (or hardcoded) model sets — is its own feature, specced separately in [Articles.md](Articles.md). Wikilinks would be [[article:italian_bootlegs]]. The `/article/italian_bootlegs` page would have a dynamic list of all models that are unlicensed copies, whose Corporate Entity is from anywhere in Italy.
