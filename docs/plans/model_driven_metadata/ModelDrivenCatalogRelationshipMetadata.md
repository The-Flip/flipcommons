# Model-Driven Catalog Relationships

## Status: deferred

**This plan is not being implemented now.** The acute wins it was built to capture are being landed by [ProvenanceValidationTightening.md](../types/ProvenanceValidationTightening.md) as a hand-maintained unified registry. That's enough value for now; the additional machinery proposed here doesn't yet earn its keep.

What PVT captures from this doc's scope:

- Consolidation of `_entity_ref_targets` + `_literal_schemas` + `_relationship_target_registry` into a single `_relationship_schemas` registry.
- The silent-data-loss fixes on the provenance write path (malformed relationship claims misclassifying as `EXTRA`; alias/abbreviation namespaces lacking schemas).
- The identity-vs-`UniqueConstraint` cross-check at `ready()` — the one load-bearing check from this doc that works equally well against a hand-maintained registry.
- All 17 (namespace, subject_content_type) schemas registered explicitly, with spec-compatible shape (`through_model`, `subject_fks`, identity labels).

What this doc would add on top that PVT does not:

- Declarations co-located on model classes instead of in one registration function.
- Generic spec-driven resolver collapsing `M2M_FIELDS` + `_parent_dispatch` + most of `_custom_dispatch`.
- `ClaimThroughModel` marker base for discovery.
- Self-parent M2M promotion (Theme.parents, GameplayFeature.parents).

**Trigger for revisiting.** A second independent consumer of this metadata — named candidate: frontend edit metadata actually being built, not hypothetical. Different subsystem, different release cadence, clears the umbrella doc's ≥2-consumers test. Today's consumers all live on the backend claim pipeline and don't meet that bar.

**Migration path if revived.** Mechanical. Replace the 17-line `register_catalog_relationship_schemas()` body with a `ClaimThroughModel.__subclasses__()` walk that builds the same `RelationshipSchema` objects from each model's declared spec. No consumer code changes; the same startup validator runs; the same audit script works unchanged.

**Pieces from this doc that stay relevant regardless:**

- **Identity declared, not derived** — landed in PVT as `register_relationship_schema`'s identity labels + startup validator.
- **Generic resolver contract semantics** (`is_active=True` pre-filter before winner selection, retractions are active `exists=False` claims, winner-per-`(object_id, claim_key)` priority ordering, FK-existence carve-out for `exists=False`) — describe the correct claim-resolution behavior regardless of who owns the schema. Belongs in resolver code comments or a sibling doc ([ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md), which makes the read-side case for driving resolution off this spec), not in this deferred plan.
- **[SeriesCreditClaims.md](../SeriesCreditClaims.md)** — independent provenance-compliance fix; stands on its own. Not gated by anything here.

**Not elevating to their own plan docs:** the self-parent M2M promotion is a ~20-line engineering cleanup. Do it opportunistically next time someone is in the resolver code; it doesn't gate anything.

---

_The remainder of this doc is the full design as it stood at the deferral decision. Kept intact so the design work isn't lost, and so if the trigger condition is met, revival is a read-and-implement, not a redesign._

---

## Background (parent doc)

Child doc to [ModelDrivenMetadata.md](ModelDrivenMetadata.md). The umbrella doc establishes the principle ("Django model is source of truth; one axis, one typed spec"). This doc is the design for the `catalog_relationship_spec` axis — the typed spec that replaces the six drift surfaces catalogued as Cluster 1 in the umbrella.

## Scope

`catalog_relationship_spec` describes how a **catalog-app through-model** maps to a claim namespace + payload. Consumed by the claim resolver, provenance validation, and (eventually) frontend edit metadata.

Explicitly **out of scope**:

- **`EntityMedia`** (lives in `apps.media`). `apps.media` is peer-isolated from `apps.catalog` per [AppBoundaries.md](../../AppBoundaries.md); declaring a catalog-owned spec on a media-app model would violate that boundary. Media attachment gets its own axis (likely `MediaAttachmentSpec` in the media app) if and when it needs one.
- **Alias models** (ThemeAlias, GameplayFeatureAlias, etc.). These are flat FK rows, not through-models. They already have their own discovery pattern in `_alias_registry` and a different claim shape. Covering them would require a second set of fields on the spec; keep them on a separate axis.

This doc does **not** redesign [ProvenanceValidationTightening.md](../types/ProvenanceValidationTightening.md) or [CatalogResolveTyping.md](../types/CatalogResolveTyping.md) — those are downstream consumers. It also does not design `citation_source_spec`; that's a separate axis and will get its own sibling doc.

## What this replaces

Five Cluster 1 violations from [ModelDrivenMetadataViolations.md](ModelDrivenMetadataViolations.md), plus part of a sixth:

- `_entity_ref_targets` (fully)
- `_relationship_target_registry` (fully)
- `M2M_FIELDS` (fully)
- `_parent_dispatch` (fully)
- `_custom_dispatch` (fully)
- `_literal_schemas` — the **abbreviation** portion only. The alias portion remains until the alias-axis follow-up lands (see [ModelDrivenMetadata.md](ModelDrivenMetadata.md)'s Silver-pattern note on `_alias_registry`).

Each entry answers the same question in a different dialect: _given a claim namespace, what through-model does it live on, and how do I build/resolve/validate it?_ `CatalogRelationshipSpec` subsumes them for through-model-backed relationships. Bespoke-resolver dispatch state (`_custom_dispatch` now stores `(entity model, resolver function name)` after the signature-standardization sweep) is orthogonal to the spec — see "Resolver strategy" below.

One consequence: runtime helpers that need the **full** set of relationship namespaces for claim classification — `get_relationship_namespaces()` and similar — must union two sources during the transition: namespaces derived from `CatalogRelationshipSpec` + namespaces derived from the alias registry. Once the alias axis lands, both sources become model-derived and the union collapses to a single walk.

## The spec

### Example

```python
class MachineModelGameplayFeature(models.Model):
    ...
    catalog_relationship_spec: ClassVar[CatalogRelationshipSpec] = CatalogRelationshipSpec(
        namespace="gameplay_feature",
        subject=SingleSubject("machinemodel"),
        identity_fields=("gameplayfeature",),
        value_key_overrides={"gameplayfeature": "gameplay_feature"},
        optional_value_fields=("count",),
    )


class Credit(models.Model):
    ...
    catalog_relationship_spec: ClassVar[CatalogRelationshipSpec] = CatalogRelationshipSpec(
        namespace="credit",
        subject=XorSubject(("model", "series")),
        identity_fields=("person", "role"),
    )
    # Bespoke resolution (XOR branch write) registered in apps/catalog/resolve/_bespoke.py.
```

### Design rule: identity is declared and cross-checked

The non-subject fields that compose the claim_key identity are declared explicitly on the spec as `identity_fields=(...)` and cross-checked against the model's `UniqueConstraint`(s) at `ready()` time.

A purely derived formulation — "identity is always `UniqueConstraint.fields − subject.fks`" — was considered and rejected. The deciding argument is defensive: we want UC edits that affect claim identity to be **noisy**. Under derivation, a future edit to a `UniqueConstraint` for DB-integrity reasons silently redefines claim identity, breaking `claim_key` stability with no alarm. Under explicit declaration, the same edit fails at startup with a clear mismatch between `identity_fields` and the UC residual, forcing whoever changed the UC to acknowledge the semantic impact (by updating `identity_fields` or reverting the UC edit). The DRY cost — one tuple per spec — is small; the cost of silent drift would be large.

The `ready()`-time validator asserts:

1. Exactly one `UniqueConstraint` (or, for XOR subjects, exactly one conditional UC per subject branch) whose fields are exactly `subject.fks ∪ identity_fields`.
2. For XOR subjects, both conditional UCs yield the same `identity_fields`.
3. All referenced field names (subject, identity, payload) resolve via `_meta`.

Any mismatch raises `ImproperlyConfigured` at startup.

### Discovery: `ClaimThroughModel` abstract marker base

Validating "every claim through-model declares a spec" requires enumerating the universe of claim through-models — not just the ones that happen to declare the attr. A `hasattr` walk only finds specs that exist; it cannot catch a missing one.

The universe is defined by an abstract marker base:

```python
class ClaimThroughModel(models.Model):
    """Marker base for through-models whose rows are materialized from claims."""

    class Meta:
        abstract = True
```

Every claim-bearing through-model (`MachineModelTheme`, `Credit`, `CorporateEntityLocation`, `ThemeParent`, `GameplayFeatureParent`, etc.) inherits from it. Discovery is `apps.get_models()` filtered by `issubclass(ClaimThroughModel)` and non-abstract — the same app-registry pattern [`core/entity_types.py`](../../../backend/apps/core/entity_types.py) uses. `ready()` asserts every discovered subclass declares `catalog_relationship_spec`; a subclass without one fails at startup.

This is a **discovery** ABC, not a **shape taxonomy** ABC. It has no abstract methods, no subtype-specific behavior. The "Abstract base classes" rejection below refers to a different design (taxonomy-by-subclass with shape-enforcing abstract methods), which still stands. The marker base is just the mechanism for asking "which models is this validator responsible for?"

### Fields

- **`namespace`** — the namespace string, often differs from the Django field name (`"gameplay_feature"` vs field `gameplayfeature`). `"abbreviation"` is shared across `TitleAbbreviation` and `MachineModelAbbreviation` — runtime lookup is keyed by `(namespace, subject_content_type)` for shared-namespace cases.
- **`subject`** — a tagged union declaring which FK(s) point to the parent/owner rather than the identity side. Django can't tell these apart, and self-parent through-models (`ThemeParent` after promotion) have two FKs to the same model that are only distinguishable semantically. Two variants:
  - **`SingleSubject(fk_name)`** — one FK names the subject, e.g. `SingleSubject("machinemodel")`. Covers the vast majority of through-models.
  - **`XorSubject((fk_a, fk_b))`** — exactly one of two nullable FKs is non-null per row (e.g. `Credit.model` XOR `Credit.series`). Validator requires both a matching pair of conditional `UniqueConstraint`s and a `CheckConstraint` enforcing the XOR.
  - Polymorphic subjects (`ContentType` + `object_id`) are **not** in the spec — the only catalog-app case would have been `EntityMedia`, which is out of scope.
- **`identity_fields`** — tuple of model field names that, together with the subject FK(s), compose the row's uniqueness and the claim_key identity. Declared explicitly (see "Design rule" above) and cross-checked against the model's `UniqueConstraint` at `ready()`.
- **`value_key_overrides`** — map from Django field name to JSON value_key when they differ.
- **`optional_value_fields`** — model fields that participate in the claim payload as optional keys (`count` on `MachineModelGameplayFeature` is the only current example) vs. pure model bookkeeping. Fields in this set are neither subject nor identity; they're non-identity stored state written from the claim payload.

The spec deliberately carries **no `resolver` field**. Resolution behavior is a sibling concern tracked in `apps/catalog/resolve/_bespoke.py`; see "Bespoke resolvers" below. Keeping the spec as pure data avoids a circular import (models would otherwise have to import resolver callables that themselves import models) and preserves the spec's cohesion around "what a claim for this relationship looks like" rather than drifting toward a grab bag.

Not currently a field: there's no `extra_value_fields` for claim-payload-only keys that aren't model fields. The original motivating example (`alias_display`) lives on alias models, which are out of scope. Reinstate if a real need emerges inside the through-model set.

There is also no `id_kwarg`. Previously `_custom_dispatch` carried a per-resolver kwarg name (`model_ids` vs `entity_ids`) because bespoke resolvers were written without a naming convention. That indirection is gone — all bespoke resolvers now take `subject_ids` after the standardization sweep.

## What the derived schema validates, and when

The derived `RelationshipSchema` is used at **two distinct times**, and it's worth being explicit about what each covers. The main payoff of a typed schema over the status quo is shifting validation leftward — catching malformed claims at write time rather than discovering them at bulk materialization.

### At `ready()` (structure validation — catalog-side)

- Every `ClaimThroughModel` subclass declares `catalog_relationship_spec`. (Enabled by the marker base in "Discovery" above.)
- All field names referenced by the spec (`subject.fks`, `identity_fields`, `optional_value_fields`, `value_key_overrides` keys) resolve via `_meta`.
- `identity_fields ∪ subject.fks` exactly matches a `UniqueConstraint` on the model.
- `XorSubject` specs have both matching conditional UCs and an XOR `CheckConstraint`.
- Every `XorSubject` spec has a `BESPOKE_RESOLVERS` entry.
- No two specs share `(namespace, subject_content_type)` — shared-namespace cases (`abbreviation`) are disambiguated by content_type, and that uniqueness is enforced.

### At claim write time (payload validation — provenance-side)

This is the richer case, and the one that closes today's drift between "claim accepted" and "claim produces valid through-row." The derived schema drives:

- **Required value keys.** A `credit` claim must have `{person, role}`; absence fails at write. Derived from `identity_fields` + any required `optional_value_fields`.
- **Value key types and constraints.** `count` on `MachineModelGameplayFeature` is `int >= 0`; a string or negative number fails at write. Derived from model field types + `CheckConstraint`s + field validators where practical.
- **Allowed namespaces per subject content type.** A claim on `Title` with `field_name="credit"` fails — credits only bind to `MachineModel` / `Series`. Derived from the `(namespace, subject_content_type)` lookup table.
- **FK target existence (positive claims only).** `{person: <pk>}` on a positive claim (`exists=True` or absent) must reference a real `Person`. Existing resolvers log-and-skip on unresolved FKs; pushing this leftward into claim validation turns a silent skip into a write-time rejection. **Retractions (`exists=False`) are exempt** — the target row may already have been deleted, and a retraction is a statement about the previous assertion, not about current target existence. This carve-out preserves existing behavior; there is explicit test coverage in [`test_validation.py`](../../../backend/apps/catalog/tests/test_validation.py) for retractions against deleted targets. Identity keys are still required on retraction claims so resolution knows which row to remove.
- **Value key surface.** Unknown keys in `value` (e.g. `{person, role, typo}`) fail, so typos don't accumulate in stored claim payloads.

Two write-time failures are genuinely out of scope for this layer and stay at resolution time: (a) cross-table dedup (`ModelAbbreviation` vs `TitleAbbreviation` — the conflict isn't visible from the one claim alone), and (b) subject existence (the subject FK is in the `Claim`'s generic-relation columns, not the payload, and already has its own validation path).

### Why this matters

Today, a claim with `count=-1` is accepted, stored, and crashes bulk materialization downstream. A claim with `field_name="credit"` on a `Title` is accepted and silently ignored. Both produce wasted ingest work and split the "validation" story across multiple write paths — exactly the pattern [ValidationFix.md](../ValidationFix.md) flags. The derived schema gives provenance a single source to validate against, at the point of write.

## Prerequisite: promote self-parent M2Ms

Most M2Ms in this codebase already use explicit through-models (`MachineModelTheme`, `Credit`, `CorporateEntityLocation`, etc.). The only hidden auto-throughs are the self-parent M2Ms on `Theme.parents` and `GameplayFeature.parents`. Promoting these to `ThemeParent` and `GameplayFeatureParent` is a prerequisite to a clean spec rollout.

This is engineering uniformity, not a provenance fix. These relationships already go through claims today — [`ingest_pindata.py`](../../../backend/apps/catalog/management/commands/ingest_pindata.py) writes `field_name="parent"` claims during ingest, and [`_resolve_parents`](../../../backend/apps/catalog/resolve/_relationships.py) materializes them into the auto-through rows. The claims infrastructure is fine; it's the representation that needs cleanup.

Benefits:

- **Drops a fragile self-ref code path.** [`_resolve_parents`](../../../backend/apps/catalog/resolve/_relationships.py) currently builds column names via `f"from_{model_name}_id"` / `f"to_{model_name}_id"` against Django's auto-through naming convention. Explicit through-models give regular FK names.
- **No special-case dispatch** in the generic spec-driven resolver. `ThemeParent` becomes indistinguishable from `MachineModelTheme` to the dispatcher.
- **Future-flex.** Explicit through-models can acquire fields later (sort order, parent-kind metadata, rationale) without data-moving migrations.
- **Finishes a pattern that's already the norm** — nine of ten through-models are explicit; these are the outliers.

Execution cost is near-zero because the project is pre-launch and the DB is resettable, but that's why now is cheap, not why to do it. Two small migrations create the through-models; [`_resolve_parents`](../../../backend/apps/catalog/resolve/_relationships.py) retires in favor of the generic spec-driven resolver.

## Worked inventory

The full inventory of catalog-app through-models and their proposed `CatalogRelationshipSpec` literals has been sketched and cross-checked against current `UniqueConstraint`s. All ten (including the two self-parents after promotion) fit the spec shape above: for each, the declared `identity_fields` plus the subject FK(s) exactly match an existing `UniqueConstraint`. Credit's XOR validates by asserting both conditional UCs reduce to the same `identity_fields=("person", "role")` residual.

**One finding, now tracked as a prerequisite:** Credit's Series branch is not wired through claims today — the resolver hardcodes `MachineModel` ContentType and the sole Series-credit writer (`ingest_pindata.py`) inserts `Credit(series=...)` rows directly, bypassing provenance. This is a pre-existing violation of the "all catalog fields are claims-based" rule, independent of the spec. It must land before the spec cutover, since the spec's claim that Credit fits `XorSubject` is only honest once both branches actually flow through claims end-to-end. Scoped in its own doc: [SeriesCreditClaims.md](../SeriesCreditClaims.md).

## Resolver strategy

A separate audit of all bespoke resolvers in `backend/apps/catalog/resolve/` showed that the apparent signature diversity was mostly cosmetic: `model_ids` vs `entity_ids` was pure naming; one unused stats-dict return could be dropped; entity-type hardcoding goes away once the dispatcher picks the spec by `(namespace, subject_content_type)`; self-referential column naming disappears once `Theme.parents` and `GameplayFeature.parents` are promoted to explicit through-models.

The stronger finding: **most bespoke resolvers disappear entirely** once the generic resolver reads the spec. Theme, tag, reward_type, corporate-entity-location, gameplay_feature (its `count` fits `optional_value_fields`), and the promoted parent through-models all collapse into one spec-driven generic resolver. The only remaining bespoke cases are those with internal semantic logic that can't be expressed declaratively:

- **`Credit`** — XOR subject write (which FK branch gets populated per row)
- **`ModelAbbreviation`** — cross-table dedup against `TitleAbbreviation` (a model abbreviation is suppressed if its title already has that abbreviation)

Possibly one or two more will surface during implementation. Those cases are registered in the bespoke map (below); everything else goes through the generic path.

### Generic resolver contract

The generic resolver commits in writing to the following semantics. Any bespoke resolver should match them on the parts it doesn't need to override, so swapping between generic and bespoke is behavior-preserving wherever possible.

1. **Winner-per-(`object_id`, `claim_key`).** Claims for a given `(content_type, object_id, field_name)` are grouped by `claim_key`; within each group the resolver picks one winner by: `effective_priority DESC`, then `created_at DESC`, then `pk DESC` as a stable tiebreak. This is the same ordering used today by [`_resolve_parents`](../../../backend/apps/catalog/resolve/_relationships.py#L760) and [`resolve_all_credits`](../../../backend/apps/catalog/resolve/_relationships.py#L320).
2. **`exists=False` retractions beat lower-priority positive claims.** A retraction claim that wins its `claim_key` group removes the row from the materialized set, even if a lower-priority positive claim exists. A positive claim that wins suppresses any retractions below it. The retraction check runs **after** winner selection, not as a pre-filter.
3. **Pre-filters before winner selection.** Claims are filtered to `is_active=True` AND `source.is_enabled=True` before priority grouping. `is_active=False` means the claim has been superseded by a newer one from the same author or retracted administratively — it is no longer part of the live set. Disabled sources drop out likewise. Do not confuse inactive claims with retractions: **retractions are active claims whose payload has `exists=False`**, and they compete in priority ordering per bullet 2.
4. **Idempotent sync via diff.** The resolver computes the desired set of through-rows from winners, compares against the existing set, and emits `bulk_create` for additions and `filter(pk__in=...).delete()` for removals. It never touches rows outside the subject scope.
5. **Subject scoping.** When called with `subject_ids={...}`, the resolver processes only those subjects — both on the desired side (claim filter) and the existing-rows side (row filter). The two filters must use the same subject set, or deletions will leak outside the scope.

**Latent inconsistency this surfaces.** [`resolve_all_corporate_entity_locations`](../../../backend/apps/catalog/resolve/_relationships.py#L852) today filters `is_active=True` before selecting winners and unions results without winner-per-`claim_key` priority ordering. Under the generic contract, the same inputs would produce (potentially) different outputs: a lower-priority active claim that currently materializes would be suppressed by a higher-priority inactive one. This is a **deliberate fix** of a latent inconsistency, not a regression — the refactor normalizes to the semantics Provenance.md describes as correct. Worth calling out in the cutover so anyone validating behavior knows to expect it.

### Bespoke resolvers

Bespoke resolution lives in a dedicated module, e.g. `backend/apps/catalog/resolve/_bespoke.py`:

```python
BESPOKE_RESOLVERS: dict[type[models.Model], Callable[..., None]] = {
    Credit: resolve_credits,
    ModelAbbreviation: resolve_model_abbreviations,
    # …one or two more may be added during implementation
}
```

The dispatcher (walking through-models with a `catalog_relationship_spec`) checks `BESPOKE_RESOLVERS.get(ThroughModel)` first; a hit delegates; a miss falls through to the generic spec-driven resolver. All bespoke resolvers use the canonical `(subject_ids: set[int] | None = None) -> None` signature established by [commit 2eea1ebaf](https://github.com/deanmoses/pindata/commit/2eea1ebaf).

Why a sibling map rather than a `resolver` field on the spec:

- **Dependency direction.** Resolvers import models; putting a resolver callable on the model class inverts that, forcing lazy imports or string references. The sibling map keeps the arrow pointing the right way — specs stay in `models/`, resolvers stay in `resolve/`, and only `resolve/` knows about the mapping.
- **Cohesion.** The spec answers "what does a claim for this relationship look like?"; the resolver answers "how do we materialize claims into rows?" Different subsystems, different cadences of change.
- **Pure-data spec.** Keeps the door open for codegen to non-Python consumers without carving out callable fields.

The `ready()`-time validator cross-checks what's _derivable_:

1. Every entry in `BESPOKE_RESOLVERS` must reference a through-model that declares a `catalog_relationship_spec`. A map entry pointing at an unspec'd model fails at startup.
2. Every spec with `XorSubject` must have a bespoke entry. The generic resolver can't pick which FK branch to write, so XOR implies bespoke, and this is derivable from the spec shape alone.

Other bespoke-needs — cross-table dedup (e.g. `ModelAbbreviation` vs `TitleAbbreviation`), multi-row semantics, side-effects into non-claim tables — are only knowable from the resolver's _behavior_. For those, the map entry is itself the declaration; there's no derivable predicate to cross-validate against. The failure mode is: if you write a bespoke resolver and forget to register it, the generic path runs and produces wrong results. This is visible in tests, not at startup.

Discoverability cost: a reader looking at `Credit` alone doesn't see the resolver pointer. Mitigated by keeping the bespoke map small (2–4 entries expected) and co-located in one file, and by a short comment on the model pointing at `_bespoke.py` when a bespoke resolver is registered.

### Status

**Landed** (commit `2eea1ebaf`, "refactor(resolve): standardize bespoke resolvers on subject_ids kwarg"):

- `entity_ids` / `model_ids` → `subject_ids` across all bespoke resolvers.
- Dropped the unused `dict[str, int]` return from `resolve_all_corporate_entity_locations`.
- Collapsed `CustomDispatchSpec.id_kwarg_name`; the tuple is now `(entity model, resolver function name)`.

**Still ahead, as part of `CatalogRelationshipSpec` implementation itself:**

- Thread the spec into a generic resolver.
- Collapse `_custom_dispatch`, `_parent_dispatch`, and most of `M2M_FIELDS`.
- Promote `Theme.parents` and `GameplayFeature.parents` to explicit through-models (see "Prerequisite" above).

## Open design questions

### App boundary: catalog vs. provenance

`AppBoundaries.md` keeps provenance peer-isolated from catalog. The previous `_relationship_target_registry` mechanism preserved this via _inversion_: catalog's `ready()` called `register_relationship_targets()` to push mappings into provenance; provenance never imported catalog. The current `_relationship_schemas` registry keeps the same boundary-preserving push shape with a richer schema.

A naïve reading of "validation reads derived schemas from model-owned specs" would break that boundary. The preserved design is:

1. Catalog app's `ready()` walks claim through-models, derives `RelationshipSchema` instances from each `CatalogRelationshipSpec` + `_meta`.
2. Catalog pushes those derived schemas into a narrow provenance-side registry API (same shape as today, narrower contract).
3. Provenance validates against its registry without importing catalog models.

The spec stays model-owned (what this doc argues for); provenance stays peer-isolated (what AppBoundaries.md requires). The boundary-preserving push pattern must stay — see the Implications section below for how it fits with ProvenanceValidationTightening's rewrite.

## Implications for ProvenanceValidationTightening.md

[ProvenanceValidationTightening.md](../types/ProvenanceValidationTightening.md) as currently designed proposes a unified `_relationship_schemas` registry — one registry to replace three. That's strictly better than the status quo, but per the umbrella principle, it's still the wrong shape.

Redesigned under this principle:

- A narrow provenance-side registry of `RelationshipSchema` instances exists at runtime — it's what provenance reads during validation. What changes is how it's populated: canonical declarations live on through-model classes as `catalog_relationship_spec` attrs, catalog's `ready()` walks those and derives the schemas, and a narrow push API moves them into provenance. The registry is a derived cache, not a second source of truth, and the app boundary stays intact (see the "App boundary" open question above).
- Every claim through-model — including the newly-explicit `ThemeParent` and `GameplayFeatureParent` — declares a single `catalog_relationship_spec = CatalogRelationshipSpec(...)` class attr.
- Catalog's `ready()` walks claim through-models (discovered via the `ClaimThroughModel` abstract marker base — see "Discovery" below), derives `RelationshipSchema` instances from `_meta` + each declared `CatalogRelationshipSpec`, and pushes them into the provenance-side registry via a narrow API. Keyed by `(namespace, subject_content_type)` for shared-namespace cases like `abbreviation`. Identity comes from the spec's declared `identity_fields`; the model's `UniqueConstraint` is cross-checked against it but is not the identity source.
- Catalog-side `ready()` validator asserts every `ClaimThroughModel` subclass declares a `CatalogRelationshipSpec`, that referenced fields resolve via `_meta`, and that the declared subject and `identity_fields` together match the model's `UniqueConstraint` shape (one matching UC for `SingleSubject`; matching conditional UCs plus an XOR `CheckConstraint` for `XorSubject`).
- Provenance validates against its registry; same rejection conditions as currently specced. Provenance does not import catalog models.
- **Two small migrations** to promote `Theme.parents` and `GameplayFeature.parents` to explicit through-models (see "Prerequisite" above).

ProvenanceValidationTightening scope becomes: derive relationship schemas from model-owned `CatalogRelationshipSpec`s + tighten validation with the new derived schemas + the two promotion migrations. [CatalogResolveTyping.md](../types/CatalogResolveTyping.md)'s TypedDicts are still useful; the "consistency test" now compares TypedDict shapes against derived schemas (same idea, different source).

Net effect: one `CatalogRelationshipSpec` per through-model, two small migrations, **fewer** total new lines of code because the _hand-maintained_ canonical registry disappears. A thin derived cache on the provenance side remains, but its entries are mechanically projected from model-owned specs rather than declared.

## Alternatives considered and rejected

### Abstract base classes

One alternative to `CatalogRelationshipSpec`-as-data is `CatalogRelationshipSpec`-as-type-hierarchy: `ClaimThroughModel(ABC)` with `EntityRefClaim`, `LiteralClaim`, `RelationshipClaim` subclasses, each enforcing its own shape via abstract methods. Appeal: shape mismatches become import-time errors rather than first-request, and shared-namespace / XOR cases become explicit subclasses rather than conditional logic in a generic resolver.

Rejected because:

- The declarative data object can do the same validation at `ready()` time — startup failure is close enough to import-time failure for this use case.
- Several through-models straddle categories (shared-namespace abbreviations are part literal, part entity-ref-ish), which would force either awkward multiple inheritance or a catch-all subclass that defeats the point.
- Inheritance imposes a taxonomy that will fight future claim shapes; a data object lets new fields be added without moving classes around.

Data object wins on flexibility; ABC hierarchy would lock in a taxonomy we don't yet trust.

(Note: this rejects an ABC as a **shape taxonomy** — separate `EntityRefClaim` / `LiteralClaim` / `RelationshipClaim` classes with shape-enforcing abstract methods. The `ClaimThroughModel` marker base used for discovery, described in "Discovery" above, is a different thing: no abstract methods, no subtype-specific behavior, used only to make "which models does this validator cover?" answerable. Both decisions can coexist.)

### Consolidated relationship registry

Another alternative would be to accept the registry shape but consolidate the current scattered relationship metadata into a single richer registry. This was the direction proposed by [ProvenanceValidationTightening.md](../types/ProvenanceValidationTightening.md): replace `_entity_ref_targets`, `_literal_schemas`, and `_relationship_target_registry` with one authoritative `_relationship_schemas` structure.

Appeal: it is smaller than a model-owned metadata rewrite, reduces today's most obvious duplication, and gives validation/resolution/frontend metadata a single runtime schema to read.

The crucial distinction vs. what this doc actually proposes: the rejected alternative is a **hand-maintained** registry whose entries are the canonical declaration. The kept design has a **derived** registry whose entries are mechanical projections of model-owned specs. Runtime shape is similar; population strategy and ownership are opposite.

Rejected because:

- **Ownership.** Declarations still live away from the through-model that defines the relationship. Adding or changing a relationship means remembering to edit the registry separately from the model. The derived design dodges this by making the spec a class attr, which means `ready()` picks up changes mechanically.
- **Dumping-ground pressure.** A hand-maintained registry sitting between many consumers accumulates resolver hints, frontend metadata, and one-offs, because each new consumer reaches for the nearest available structure. The derived design contains this pressure by keeping the schema shape narrow and model-owned — adding a field means adding a field to every through-model, which is visible work and naturally resisted.
- **Improves one drift surface but not the root cause.** A single consolidated registry is better than three scattered ones, but still a second schema beside Django. The root cause is that the canonical declaration isn't co-located with the thing it describes.

This can still be useful as a temporary migration bridge if a direct model-owned rewrite is too large, but it should not be the final architecture.
