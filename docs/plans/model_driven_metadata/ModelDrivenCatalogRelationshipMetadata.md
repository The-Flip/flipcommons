# Disentangle Claim Resolution from Catalog

## Context

Claim resolution materializes the catalog (denormalized columns + through-tables) from the claim log. The hard mechanical work already landed in [ClaimResolutionRefactor.md](../provenance/ClaimResolutionRefactor.md): `pick_winners`/`reconcile`/`Projection`/`ThroughRowProjection` are extracted into a catalog-free `_engine.py`, and the dispatch seam (`resolve_after_mutation`, `resolve_entities_bulk`, `ResolveHandlers`, `register_resolve_handlers`) already lives in `apps/provenance/resolution/`.

This effort is the next chapter: making the **whole** resolution boundary clean enough that extracting the rest from the catalog app could be done with `git mv`, the contracts are legible, and catalog can no longer leak into the generic machinery. The goal is the best system, not the most direct disentanglement.

The boundary is already mostly built. What remains:

1. **The relationship tier is not model-driven.** `resolve/_relationships.py` and `resolve/_dispatch.py` hand-write a projection _builder_ per namespace and hard-name ~15 concrete catalog models (`MachineModel`, `Credit`, `Theme`, …). pyproject.toml says so itself: _"the relationship/dispatch resolvers still bind MachineModel … it awaits the deferred relationship declaration vocabulary."_ This is the load-bearing entanglement — and a direct violation of the CLAUDE.md "catalog must be model-driven" rule for relationships.
2. **Contract hygiene.** One domain constant (`IMAGE_FIELDS`) sits in the would-be-generic core.

Scope is the **resolution layer only**; we aren't going to do a broad refactor of all of provenance here.

## <a id="related_docs"></a> Relation to adjacent work

This is the rung-4 model-driven relationship tier under the [ModelDrivenClaimResolution.md](../model_driven_metadata/ModelDrivenClaimResolution.md) umbrella vision: resolution lives in provenance, catalog declares its schema, and the dispatch table is computed from model metadata rather than hand-enumerated.

It builds directly on the registry [ProvenanceValidationTightening.md](../types/ProvenanceValidationTightening.md) shipped — `register_relationship_schema` / `RelationshipSchema` / `FkTarget` — which this work derives both the validation schema and the resolution projection from. Two pieces PVT scopes to the spec work land here: the identity-vs-`UniqueConstraint` cross-check (REF2) and `(namespace, subject_ct)` precision for shared namespaces (latent until value-key shapes diverge across subjects).

`claim_relationship_spec` follows the model-driven ClassVar pattern [ModelDrivenClaimsMetadata.md](../model_driven_metadata/ModelDrivenClaimsMetadata.md)'s `claim_fk_lookups` established — a per-model declaration on the model, consumed generically by shared infrastructure.

## Goals

1. **Stop the bleeding, both directions.** Import-linter ratchets so neither the generic resolution core imports catalog, nor provenance imports catalog.
2. **Model-driven relationship tier.** One declaration per relationship drives both validation schema and resolution projection; the generic builder names no concrete model.
3. **Clear, strongly-typed public contracts** to provenance and claim resolution — one import path per capability, no leaked privates.
4. **Clear, strongly-typed internal layer contracts** — write → rank → engine → dispatch → side-effect handlers, each a named typed seam.
5. **Easy to reason about** — one conceptual home per concept; "where does X live" has one answer.

**Success litmus (not a required step):** the catalog-free resolution core can be `git mv`'d into `provenance/resolution/` with zero edits to the moved files. The move itself stays out of scope.

## What is already clean (do not redo)

- `_engine.py` (`reconcile`, `pick_winners`, `Projection`, `ThroughRowProjection`, converters) — catalog-free, import-linter-pinned.
- The provenance dispatch seam — `resolve_after_mutation`, `resolve_entities_bulk`, `ResolveHandlers`/`PerEntityResolver`/`BulkResolver`, `register_resolve_handlers`. Correct boundary; leave alone.
- `_entities.py`, `_helpers.py`, `_claim_values.py` — already fenced from catalog domain by the "Generic resolver core" contract.
- Side-effect placement: cache invalidation and markdown sync are correctly behind catalog's registered handlers / domain-neutral. The **only** domain impurity in the core is `IMAGE_FIELDS` (PRE3).

## Design

### <a id="design-patterns"></a> Design patterns this builds on

The merge-and-materialize substrate this work configures is already named and single-sourced in ClaimResolutionRefactor.md — see [Design patterns & data structures](../provenance/ClaimResolutionRefactor.md#design-patterns) (desired-state reconciliation / the controller loop, materialized-view / IVM, the priority-ranked LWW register + tombstoned element-set merge, the `pick_winners` fold, level-triggered idempotence) and [The design](../provenance/ClaimResolutionRefactor.md#design) (the `reconcile` loop and the typed vocabulary — `Projection` / `Delta` / `MemberMap`, each `[Subject, Member, Payload]`, plus `RowState[Payload]` and `Winners[Subject, Group]`). This work reuses them unchanged; it does not restate them.

On top of that substrate it adds three constructs, named where they appear below:

- **Declarative spec + generic interpreter** — `build_through_projection` reads a typed `ClaimRelationshipSpec` and instantiates a configured `ThroughRowProjection` instead of a hand-written builder per namespace; this is rung 4 (declaration-derived dispatch) of [ModelDrivenClaimResolution.md](../model_driven_metadata/ModelDrivenClaimResolution.md)'s dispatch ladder.
- **Single source → derived twin registries** — one spec is mechanically projected into the validation schema and the resolution projection, neither a second source of truth.
- **Marker-base discovery** — `ClaimThroughModel` defines the universe of claim through-models so a missing spec fails loudly: a discovery ABC, not a shape taxonomy.

### <a id="vocab"></a> The relationship declaration vocabulary (the centerpiece)

The 7 `ThroughRowProjection` builders in `_relationships.py` vary almost entirely by **data** — subject model, through model, key columns, payload column, FK-target validation sets, conflict policy — most of it Django-introspectable from the through-model. And the existing relationship-_schema_ registry's `ValueKeySpec(name, fk_target=…)` already declares the value-key→FK-target mapping that the resolution `extract` functions re-encode by hand. So one declaration can drive both.

Declare a pure-data spec as a `ClassVar` on each through-model (CLAUDE.md "base-class ClassVar → typed spec"); the spec **types** and the marker base live in **`core`** — the codebase's model-driven-metadata substrate (`entity_types`, the claim type aliases, `LinkableModel`), below every consumer, and the only neutral home the catalog-free engine can import. The spec is generic vocabulary; only its instances are pinball, so it is no more provenance-specific than catalog-specific. (`provenance/model_bases`, sibling to `ClaimControlledModel`, was the other candidate — also lift-out-ready — but core wins: the read-surface consumers are model metadata, not claim machinery, and a neutral home keeps every import arrow pointing down.) Catalog through-models import the spec type from core; the generic builder (in `provenance/resolution`) imports it from core too — arrows point down into core, allowed everywhere.

```python
# apps/core — domain-neutral vocabulary. Threads existing aliases
# (ClaimFieldName, ClaimValueKey, IdentityPartName from core/provenance types;
# ScopePolicy the existing enum, relocated here) rather than bare str — "types document intent".
type ColumnName = str   # a through-table column / FK attr / model field name (engine's ColumnNames = tuple[ColumnName, ...])

class ClaimThroughModel(models.Model):
    claim_relationship_spec: ClassVar[ClaimRelationshipSpec]
    class Meta:
        abstract = True

@dataclass(frozen=True, slots=True)
class SingleSubject:     fk_name: ColumnName                       # "machinemodel", "title"
@dataclass(frozen=True, slots=True)
class XorSubject:        fk_names: frozenset[ColumnName]           # {"model", "series"} — unordered, validated to 2
type SubjectSpec = SingleSubject | XorSubject
# SelfParentSubject(from_fk, to_fk) — ordered child → parent — is added by the POST parent-promotion
# step, when Theme/GameplayFeature parents become explicit ClassVar through-models. Until then parents
# ride the kept _parent_projection, so the REF vocabulary needs no self-parent variant.

@dataclass(frozen=True, slots=True)
class MemberField:
    field: ColumnName                            # through-model column: "theme", "person", "value"
    value_key: ClaimValueKey | None = None       # JSON value-dict key when ≠ field ("gameplay_feature")
    identity: IdentityPartName | None = None     # claim_key identity label
    lookup_field: ColumnName = "pk"              # FK target lookup; the target MODEL is introspected, never named

@dataclass(frozen=True, slots=True)
class PayloadField:
    field: ColumnName                            # "count"
    value_key: ClaimValueKey | None = None
    nullable: bool = False

@dataclass(frozen=True, slots=True)
class ClaimRelationshipSpec:
    namespace: ClaimFieldName
    subject: SubjectSpec
    members: tuple[MemberField, ...]             # ready() enforces 1 (plain/literal/parent) or 2 (credit)
    payload: tuple[PayloadField, ...] = ()
    ignore_conflicts: bool = False
    scope: ScopePolicy = ScopePolicy.SUBJECTS
# (case_fold / display_member are NOT here: aliases — the only case-folded shape — stay bespoke in REF and
#  become generated-column through-rows in POST, so neither phase needs a spec field for case-folding.)
```

A single generic `build_through_projection(subject_model, through_model) -> ThroughRowProjection | None` reads the spec and configures `ThroughRowProjection`, reusing the existing `_engine.py` converters (`_int_from_column`, `_str_from_column`, `_int_or_none_from_column`, `_one_column`, …). Codecs are chosen by `len(members)`/`len(payload)`. The "skip when target vocabulary unseeded" guard (today Credit-only) generalizes to "any required FK set empty → return `None`". The builder dispatches on the `SubjectSpec` union with `match`/`case` — the sanctioned closed-union dispatch, distinct from the `isinstance`-on-model smell the model-driven rule forbids.

This is a declaration→executor split, **not** a second copy of the engine. The spec speaks **model-attribute** names (`field="theme"`); `ThroughRowProjection` (in `_engine.py`) speaks **DB columns + codecs** (`key_columns=("theme_id",)`); `build_through_projection` is the single bridge — it derives columns from `_meta` and selects codecs from `_engine`'s converters, so the spec never restates a column or codec the engine already owns. The redundancy the spec retires lives in `_relationships.py`, not `_engine.py`: `M2MFieldSpec`/`M2M_FIELDS` is a hand-maintained partial precursor of `ClaimRelationshipSpec`, and the per-shape `_*_projection` builders are its hand-written lowering — both deleted in REF4. `_engine.py`'s through-row machinery (`ThroughRowProjection`, the converters, `reconcile`) is generic and stays.

Whether a member is an FK (validated against a target-PK set) or a literal string is **introspected** from `through_model._meta.get_field(field)` — the spec carries no model-class reference, so it stays a pure ClassVar with no import-order or circular-import hazard (`Credit.role` uses the string FK `"CreditRole"` for exactly this reason). The validation schema's `FkTarget` (for write-time existence checks) is built catalog-side during the `ready()` derivation, where importing it from `provenance.validation` is allowed; `provenance.resolution` never imports it, keeping the two same-layer siblings uncoupled.

Credit (compound key) and ModelAbbreviation fit the generic builder: the XOR subject resolves via `subject_column` selection plus `ThroughRowProjection.read`'s NULL-subject exclusion, and a model's abbreviations resolve claim-locally. Three shapes don't flow through the generic ClassVar path in REF — two ride transitional paths that POST retires, one is irreducible:

- **Parent hierarchies** (`theme_parent` / `gameplay_feature_parent`) — self-referential M2Ms whose implicit `.through` carries no ClassVar. REF keeps today's `_parent_projection` (synthesized from `.through`, the `from_/to_` convention; `scope=FULL_TYPE`). The **POST parent-promotion** step makes them explicit ClassVar through-models — adding `SelfParentSubject` to the `SubjectSpec` union — and deletes `_parent_projection`.
- **`AliasProjection`** — case-folded key ≠ stored display (keyed by `value.lower()`, value kept in original case), so not a `ThroughRowProjection`. REF keeps it **as-is**, on its own `discover_alias_types()` channel (not the `ClaimThroughModel` walk — `AliasModel`s are flat FK rows, not through-models), `scope=FULL_TYPE`. The **POST alias-normalization** step adds a `value_normalized` `GeneratedField`, making aliases plain ClassVar through-rows (`key = value_normalized`, `payload = value`) and deleting `AliasProjection` — no `case_fold`/`display_member` spec field ever needed, since the DB maintains the normalized key.
- **`MediaProjection`** — content-type-keyed, imports `apps.media.models`, and is **irreducibly** bespoke (no POST step folds it in): (1) its projection is invoked through catalog's existing per-model handler / `resolve_media_attachments`, **not** an independent registration — the per-model `ResolveHandlers` seam allows one pair per model and catalog (ahead of media in `INSTALLED_APPS`) owns it, so a multi-provider seam would be required and is out of scope. The `MediaProjection` _class_ **stays catalog-side** (`catalog/resolve/_media.py`): it imports provenance ranking/models, the engine and catalog's cache, whereas media is peer-isolated from provenance (only the `MediaSupportedModel` base edge is sanctioned) and its `exhaustive` internal stack has no resolution tier — so media can't host it without a new boundary. media owns only the `EntityMedia`/`MediaAsset` target tables. (2) Its validation schema + per-entity category check are registered by the existing `MediaSupportedModel` walk, **not** derived from a `ClaimThroughModel` — media materializes into the polymorphic `EntityMedia`, which has no per-pair through-model to carry a spec.

So REF's generic builder covers the explicit ClassVar shapes; parents and aliases ride transitional paths, and after the two POST polish steps only `MediaProjection` remains bespoke. (`media_attachment`'s schema escape-hatch is independent — see REF4.)

### One declaration, two derived registries

Catalog's `ready()` keeps the inversion (provenance never imports catalog): walk `ClaimThroughModel` subclasses + `discover_alias_types()`, then derive the two registries off the one declaration — but at **different cardinality**, because the validation registry is namespace-keyed while resolution is per-through-model:

- **(a) Validation schemas — spec→schema is many-to-one.** Group specs by `namespace`, then derive one `RelationshipSchema` per namespace: union `valid_subjects` across the group, and assert value-key shape and bound parity across the members (reproducing today's cross-model agreement check — e.g. `abbreviation` spans `ModelAbbreviation` + `TitleAbbreviation` and asserts equal `max_length`; `credit`'s `XorSubject` yields `valid_subjects={MachineModel, Series}`). Harvest `max_length`/`min_value` from `_meta` exactly as `claims.py` does today, then call the **unchanged** `register_relationship_schema(...)` once per namespace. A naive per-spec registration would conflict — the registry raises on a second, differing schema for the same namespace.
- **(b) Resolution projections — per `(namespace, through-model)`.** Build the resolution registry from the same walk with `build_through_projection` partial-applied instead of hand-written fns.

Do **not** merge the two runtime registries (different keys, different cardinality) — they share the _declaration_ and the _walk_, not the cache. A consistency test locks the three representations (spec → `RelationshipSchema`, spec → projection ctor args, `_claim_values.py` TypedDicts).

### <a id="read_surface"></a> One public read surface, and its consumers

The spec registry lives in **`core`** (beside `entity_types`) and is populated by a lazy `ClaimThroughModel`-subclass walk over the app registry — so core never imports catalog. It ships **one** public query — `relationships_for(model) -> tuple[ClaimRelationshipSpec, ...]`, plus a resolved-accessor helper mapping a spec to its live reverse/M2M accessor — and every consumer calls _that_, never a private `_meta` re-walk or a second registry. Coverage boundary: because it walks `ClaimThroughModel` subclasses, in REF it returns the explicit ClassVar through-model specs only — **not** parents (synthesized via `_parent_projection`), aliases (bespoke), or media. The two POST polish steps fold parents and aliases into the walk; media stays out. So a consumer wanting _every_ claim relationship combines `relationships_for` with the still-outside paths — `discover_alias_types()` + the media walk in REF, media alone post-POST. This is the "single source, derived cache" discipline of the validation/resolution twins extended to the query surface: it is what stops the third and fourth consumer each growing a hand-maintained copy.

Most existing consumers read the **derived schema** and need no change once it is spec-derived (REF4): `provenance.claims.build_relationship_claim` (canonical identity keys), `provenance.display` (identity/payload rendering incl. `display_key`), `claim_ingest`'s patch-emit shapes, and the per-subject namespace sets the post-apply adapter reads. The read surface is for consumers needing **spec-level** facts the schema doesn't carry (through-model, accessor, shape).

**In scope here:** the read surface itself, plus the two derivations that exercise it (validation schema + resolution projection, REF4).

**Enabled, but out of this plan's resolution-layer scope** — listed so the next consumer adopts the surface instead of re-walking; each then becomes a one-spec edit rather than a second hand-edit:

- `catalog/api/export.py` — `ExportSpec.relations` already filters `get_all_relationship_schemas()` by `valid_subjects` (`export.py:289`) but still hand-lists `_rel("themes", "slugs")` / `_rel("abbreviations", "strings")` / `_rel("credits", …)`. Both halves are derivable: the **accessor** is the reverse/M2M whose `.through` is the spec's through-model; the **shape** is `"slugs"` (FK member) / `"strings"` (literal member) / `"credits"` (compound). Only genuine overrides — prefetch hints, the credit person+role serialization — stay hand-written.
- Backend relationship **edit planners** (aliases, abbreviations, parents, M2M, credits) — claim-shape construction should ride the same declaration; UI layout stays model-specific.
- Frontend relationship-editor metadata — generate from the declaration if generic edit forms grow, rather than hand-maintained TS unions.
- Entity metadata's `relationships` field — adopt only if it means _claim-controlled_ relationships; if it's navigation/display, derive a narrower projection or keep it separate.

### Why the spec is pure data

The spec carries **no resolver callable** — resolution behavior lives in `resolve/` (the generic builder + the `AliasProjection` builder), keyed off the spec. A resolver on the model would invert the dependency (models importing resolver code that imports models) and erode the spec's cohesion as a pure declaration; pure data also keeps codegen for non-Python consumers open.

#### Alternatives rejected

Alternatives weighed and rejected:

- **ABC-as-shape-taxonomy** (`EntityRefClaim`/`LiteralClaim`/`RelationshipClaim` subclasses with shape-enforcing abstract methods). A data object validates the same shapes at `ready()`; several through-models straddle categories; a class taxonomy locks in a hierarchy future claim shapes will fight. (`ClaimThroughModel` is _discovery only_ — no abstract methods — a different, kept decision.)
- **A hand-maintained consolidated registry** as the canonical declaration (what `ProvenanceValidationTightening.md` shipped as the interim). Better than scattered registries, but the declaration still lives away from the model and the registry accrues dumping-ground pressure. The derived design makes the spec a model ClassVar `ready()` picks up mechanically — the registry becomes a derived cache, not a second source of truth.

The resolution semantics themselves — winner-per-`(object_id, claim_key)` by priority then recency, `exists=false` tombstones, the `is_active` + `source.is_enabled` pre-filter, idempotent diff, subject scoping — are already implemented and single-sourced in `_engine.py` / `ranked_claims` / `member_is_present` (see [ClaimResolutionRefactor.md's invariants](../provenance/ClaimResolutionRefactor.md#invariants-to-preserve)); this work does not change them.

### <a id="internal_layers"></a> Internal layers

Five layers; the first four already typed and clean. The only new seam is the `ExtraDataHook` registry (PRE3) that evicts `IMAGE_FIELDS` from the core. Cache (behind handlers) and markdown sync (domain-neutral, `apps.core.markdown`) need no new protocol.

## The plan

### <a id="PRE"></a> PRE — clear the ground

These are independent and ship separately

#### <a id="PRE3">PRE3</a> — Evict `IMAGE_FIELDS` from the generic core

`IMAGE_FIELDS = {"opdb.images", "ipdb.image_urls", "image_urls"}` in `_image_fields.py` is pinball-domain knowledge sitting in the otherwise-generic scalar core, stamped during `_apply_claims`. Introduce an `ExtraDataHook` registry in the core — `register_extra_data_hook(field_name, hook)`, where `hook: (extra_data: JsonBody, claim: Claim, sfl_map: SourceFieldLicenseMap | None) -> None` (all core/provenance types: `JsonBody` from `core.types`, `Claim`/`SourceFieldLicenseMap` from provenance — licensing is provenance, so the hook threads license context without a catalog dependency); catalog registers `_stamp_image_license` for each image field at `CatalogConfig.ready()`. `_apply_claims` loses the `IMAGE_FIELDS` import and calls registered hooks; the `sfl_map` pre-build guard generalizes to "any field with a registered hook." This is the only place a domain identifier lives in the movable core, so it is the litmus-critical de-domaining. Pin the now-catalog-free `_image_fields` machinery under the resolver-core import-linter contract as part of this step — today it is catalog-free in practice but under no contract.

### <a id="REF"></a> REF — the model-driven relationship tier

Behavior-preserving: byte-identical materialized through-tables at every step (resolution is idempotent/level-triggered), behind the unchanged dispatch seam.

#### <a id="REF1">REF1</a> — Introduce the declaration vocabulary in provenance

Add the relationship vocabulary to **`core`**, split by kind to match core's existing layout — **not** a new `core/claims/` package, which would drag dataclasses + a model base + a registry into what is otherwise leaf-alias and abstract-base territory:

- **Structures** (`ClaimRelationshipSpec`, the subject/member/payload dataclasses, the `ScopePolicy` enum relocated from `catalog/resolve/_dispatch.py`, the `relationships_for` read surface) → a new module, e.g. `core/claim_relationships.py`. These are heavier than leaf aliases and cohesive enough to warrant their own module — but a single module, not a package.
- **Leaf aliases** the structures need (`ColumnName = str` — new, and the _element_ type of the engine's existing `ColumnNames = tuple[str, ...]` in `_engine.py`, which narrows to `tuple[ColumnName, ...]`; it does **not** replace `ColumnNames`. Plus `ClaimValueKey` relocated from `provenance.types` and `IdentityPartName` from `provenance/models/claim.py`, where it sits beside `make_claim_key`) → `core/types.py`'s existing claim section, which is deliberately dependency-free. The foundational `ClaimFieldName`/`ClaimSubjectId`/`ClaimKey`/`ClaimFieldMap`/`ContentTypeId` **stay put** there — they're cross-cutting (scalar claims, ranking, ingest), not relationship-specific, and `types.py`'s leaf-alias property is load-bearing.
- **Abstract model base** (`ClaimThroughModel`) → `core/models`, per Django.

Thread those aliases rather than bare `str`, and reuse `ScopePolicy` rather than a fresh `Literal`. Living in core (below every app), the spec carries no `provenance.validation` symbol — no `FkTarget` — by construction; FK target models are introspected from `_meta` at build time, and the alias spec is synthesized from the `AliasType` registry. No behavior yet.

#### <a id="REF2">REF2</a> — Declare specs on every catalog through-model

Add `claim_relationship_spec` to each explicit through-model (`MachineModelTheme`, `MachineModelGameplayFeature`, `Credit`, `ModelAbbreviation`, `TitleAbbreviation`, `CorporateEntityLocation`, …) and base it on `ClaimThroughModel`. Parents and aliases are **not** declared here — they ride their transitional paths (synthesized `_parent_projection`, bespoke `AliasProjection`) until the POST polish steps. Add a `ready()` validator: spec present, fields resolve via `_meta`, subject FKs ∪ identity match a `UniqueConstraint` **or `Meta.unique_together`** (Django accepts either; the POST-promoted parent through-models will use `unique_together`), XOR has both conditional UCs + the `CheckConstraint`, `members` cardinality is 1 (plain/literal) or 2 (credit). A missing spec must fail loudly, not be skipped.

Declare identity **explicitly** (as `MemberField.identity`), **not** derived as `UniqueConstraint.fields − subject.fks`. The rationale is defensive: a future UC edit for DB-integrity reasons would silently redefine `claim_key` identity under derivation; explicit declaration turns the same edit into a loud startup mismatch, forcing acknowledgement of the semantic impact. This identity-vs-UC cross-check is the one load-bearing check `ProvenanceValidationTightening.md` scopes to this work. Every current through-model's `identity ∪ subject FKs` already matches an existing `UniqueConstraint`, so the validator passes on day one and guards against future drift.

#### <a id="REF3">REF3</a> — Generic `build_through_projection`

Write `build_through_projection(subject_model, through_model)` + the codec/extractor helpers, driving entirely off the spec + `_meta`. Add a snapshot test proving it reproduces each ClassVar shape's current `_*_projection` ctor args exactly (themes, reward_type, tag, gameplay_feature, credit×2, abbreviation×2, location). Keep `_parent_projection` (synthesized parents) and `AliasProjection` (bespoke aliases) untouched — the two transitional paths the POST polish steps retire.

The generic extractor collapses three subtly different null/type guards the hand-written builders use (`type(x) is not int`, a bare `not in valid_pks`, and `claim.value or {}`) into one policy — equivalent today only because `member_is_present` filters tombstones before `extract` and write-time validation enforces scalar types. The ctor-args snapshot won't catch a divergence here, so **also** feed each shape an invalid-PK claim and a null-value claim and assert identical dropped-member behavior.

#### <a id="REF4">REF4</a> — Derive both registries from one walk; delete the hand-written builders

Rewrite `register_catalog_relationship_schemas` as a `ClaimThroughModel`-subclass walk that **groups specs by namespace** and derives one `RelationshipSchema` per namespace (spec→schema is many-to-one — union subjects, reproduce the cross-model parity asserts; see [One declaration, two derived registries](#one-declaration-two-derived-registries)). The `media_attachment` schema and its per-entity category check have no through-model, so they **stay hand-written** on the existing `MediaSupportedModel` walk — a deliberate escape-hatch parallel to the bespoke `MediaProjection`, not a regression of the model-driven goal. Rebuild `_get_relationship_registry` per `(namespace, through-model)` from the same walk with `build_through_projection`. Delete `_m2m_projection`, `_gameplay_projection`, `_credit_projection`, `_abbreviation_projection`, `_corporate_entity_location_projection` and the `M2M_FIELDS`/`M2MFieldSpec` table; fold `ScopePolicy` into `spec.scope`. `_relationships.py` shrinks to the two transitional paths — `AliasProjection` and `_parent_projection` (both retired by POST polish) — plus their builders. With the generic builder reading value-keys off the spec instead of casting, the per-namespace `_claim_values` TypedDicts (`GameplayFeatureClaimValue`, `CreditClaimValue`, `Location`/`Abbreviation`/`Parent`…) go dead — delete them; only the bespoke `AliasClaimValue`/`MediaAttachmentClaimValue` remain (catalog/media-side), so `_claim_values` is catalog payload vocabulary and does **not** hoist to provenance. Expose the registry's one public query — `relationships_for(model)` + the resolved-accessor helper — so other subsystems consume specs without re-introspecting (see [One public read surface](#read_surface)). Add the consistency test locking spec → schema → (the remaining bespoke) TypedDict.

### <a id="POST"></a> POST — uniformity polish, ratchets, and the optional move

POST1–POST2 are the deferred modeling changes (migrations) that fold the two transitional relationships into the generic ClassVar path; POST3 locks the boundary (its `provenance ⊄ catalog` half is independent and can land any time after the review removal already on `main`); POST4 is the optional move.

#### <a id="POST1">POST1</a> — Promote parent hierarchies to explicit through-models

REF leaves `Theme.parents`/`GameplayFeature.parents` as implicit self-referential M2Ms, resolved by the kept `_parent_projection` (synthesized from `.through`, the `from_/to_` convention). Promote each to an explicit through-model (`ThemeParent`, `GameplayFeatureParent`) pinned to the existing table via `Meta.db_table` + matching FK column names, so the migration is `SeparateDatabaseAndState` with **empty `database_operations`** — state-only, zero DDL, no data movement. Carry uniqueness as `Meta.unique_together` (the auto-through's existing unnamed index), **not** a named `UniqueConstraint` — one the physical table lacks would leave a state/DB name mismatch a later migration mis-targets, and would break the empty-DDL property; assert the generated migration's `database_operations == []`. Then add the `SelfParentSubject(from_fk, to_fk)` variant to the core `SubjectSpec` union, declare `claim_relationship_spec` on the two new through-models (`scope=FULL_TYPE`, uniqueness via `unique_together` — the REF2 validator already accepts it), and delete `_parent_projection` + its registry entry. Parents now flow through the generic builder. (`.parents.{add,set,remove,clear}` has no production callers — only tests, which survive Django auto-defaulting the through-model timestamps.)

#### <a id="POST2">POST2</a> — Normalize aliases into plain through-rows

REF keeps the bespoke `AliasProjection` (case-folded key ≠ stored display). Replace it with a model change: add a `value_normalized` `GeneratedField(expression=Lower("value"), db_persist=True)` to each alias model (`ThemeAlias`, `GameplayFeatureAlias`, `ManufacturerAlias`, …) with a unique constraint on the normalized key — works on prod Postgres and dev SQLite alike (Django 6 + SQLite 3.50; SQLite rebuilds the table to add a STORED generated column, invisible and a non-issue for resettable dev DBs). The DB maintains the normalized key, so aliases become plain ClassVar through-rows (`key = value_normalized`, `payload = value` in original case) declared on the alias models (now `ClaimThroughModel`s), folding into the generic builder; `AliasProjection` and the `discover_alias_types()` resolution path are deleted, and `normalize_alias_identity` stops splitting value/display (the claim carries original-case `value`; the DB derives the key). Displayed output is unchanged — a storage refactor. **Verify first:** the alias `display` override must be a case/whitespace variant of the identity value, so `lower(value)` reproduces the dedup key; if `display` can differ arbitrarily, store the identity source as its own column rather than deriving it. A data-model change beyond the resolution layer, hence POST; it pairs with POST1 to leave only `MediaProjection` bespoke.

#### <a id="POST3">POST3</a> — Import-linter ratchets, both directions

- **`provenance ⊄ catalog`**: add a forbidden contract `source_modules = ["apps.provenance"]`, `forbidden_modules = ["apps.catalog"]` (with test `ignore_imports`). provenance carries no production import of catalog, so the contract holds as written.
- **Generic resolver core ⊄ catalog** (after REF): today there are **two** catalog-free contracts — "Resolution engine primitives stay catalog-free" (`_engine` only, forbids all of `apps.catalog`) and "Generic resolver core does not import the catalog domain" (`_entities`/`_helpers`/`_claim_values`, forbids an enumerated subset). Reconcile them into **one** coherent movable-set contract: `source_modules` = the full movable set (`_engine`, `build_through_projection`, the de-domained `_image_fields` machinery, `_entities`, `_helpers`), `forbidden_modules = ["apps.catalog", …]` matching the `_engine` pattern. (`_image_fields` is pinned earlier, in PRE3; the core-resident spec types + `ClaimThroughModel` are already barred from catalog by the global app-tier layering, so they need no movable-set entry. `_claim_values` is dropped from the set — it is import-free but pinball-_shaped_ payload vocabulary, catalog's, not generic; see REF4.)

#### <a id="POST4">POST4</a> — (Optional) hoist the catalog-free core into `provenance/resolution/`

Not required — the litmus is the success measure, and POST3 proves the boundary holds. If done, keep the core **whole** as the `provenance/resolution/` package (it already is a cohesive multi-module subsystem beside the dispatch seam — do not scatter it into provenance root modules): `git mv` `{_engine, build_through_projection, dispatch registry mechanism, _helpers, _entities, _image_fields machinery}` in (the spec types + `ClaimThroughModel` already live in core; `_claim_values` is pinball payload vocabulary and stays catalog-side; `AliasProjection`/`_parent_projection` were deleted by POST1–POST2 — so none move), and restate the catalog-free contract one app down as the intra-provenance form (`apps.provenance.resolution ⊄ apps.catalog`). The catalog remainder (`_dispatch` registration, the spec-walk, side-effect handlers) keeps registering at `CatalogConfig.ready()` and imports the moved core from `apps.provenance.resolution.*`.

## <a id="end_state"></a> End-state homes

| Piece                                                                                                                                                                                                                 | Home                                                | Why                                                                                                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ClaimRelationshipSpec` + spec types, `ScopePolicy`, `ColumnName`, the `ClaimThroughModel` marker base, the `relationships_for` read surface                                                                          | **core**                                            | domain-neutral model-driven-metadata vocabulary; below every consumer                                                                                                               |
| `_engine.py`, `build_through_projection`, dispatch registry mechanism, `ExtraDataHook` registry                                                                                                                       | **provenance** `resolution/`                        | the generic interpreter, closed over the claim store; imports the spec from core; names no concrete model                                                                           |
| `claim_relationship_spec` ClassVars (incl. POST-promoted parents + normalized aliases), the `ready()` derivation walk, `_stamp_image_license` registration, `_per_entity_handler`/`_bulk_handler`, cache invalidation | **catalog** `resolve/`                              | irreducible pinball schema + config, registered into the seam                                                                                                                       |
| `MediaProjection` + the `media_attachment` schema/category registration (catalog-owned escape hatch); the `EntityMedia`/`MediaAsset` target tables (media)                                                            | **catalog** `resolve/` (+ **media** for the tables) | the projection imports provenance + engine + catalog cache; media is peer-isolated from provenance with no resolution tier, so hosting it there needs a new boundary (out of scope) |

## Critical files

- `backend/apps/catalog/resolve/_relationships.py`, `_dispatch.py`, `_engine.py`, `_entities.py`, `_image_fields.py`, `__init__.py`
- `backend/apps/catalog/claims.py` (the `ready()` registration walk)
- `backend/apps/provenance/validation.py` (`FkTarget`, `register_relationship_schema`, `RelationshipSchema`)
- `backend/apps/core/` — new `claim_relationships.py` (spec structures + `ScopePolicy` + `relationships_for`), `ClaimThroughModel` base under `core/models`, leaf aliases (`ColumnName`, relocated `ClaimValueKey`/`IdentityPartName`) added to `core/types.py`
- `backend/apps/provenance/resolution/` (generic `build_through_projection`, dispatch entries)
- `backend/apps/catalog/models/theme.py`, `gameplay_feature.py` (POST1 parent through-models); the alias models `ThemeAlias`/`GameplayFeatureAlias`/`ManufacturerAlias`/… (POST2 `value_normalized`)
- `backend/pyproject.toml` (import-linter contracts)

## Verification

- **Per phase:** run the smallest meaningful backend test set — `apps/catalog/resolve/tests/`, `apps/catalog/tests/test_resolve*.py`, `apps/provenance/tests/`. The resolution suite is the regression net: REF is correct iff materialized through-tables are byte-identical.
- **REF snapshot:** the `build_through_projection` reproduction test (REF3) + the spec→schema→TypedDict consistency test (REF4) are the core's own proofs.
- **POST1 / POST2 (migrations):** the parent promotion's `makemigrations` produces a `SeparateDatabaseAndState` with empty `database_operations` (assert it; `migrate` is a no-op on an existing DB); the alias `value_normalized` `GeneratedField` migration applies cleanly on both dev SQLite and Postgres; resolution of parents/aliases is unchanged before and after.
- **Boundaries:** `lint-imports` (import-linter) passes with the POST3 contracts; `make mypy`; `make quality`.
- **Litmus check (no move needed):** with POST3 green, grep the movable set for `apps.catalog` imports — zero confirms the `git mv` would be edit-free.
