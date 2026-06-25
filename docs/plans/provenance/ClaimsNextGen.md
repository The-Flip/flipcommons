# Claims Next Generation

## Status: 🗄️ RETIRED — superseded, nothing actionable remains

This plan is kept as a historical architecture record. Do not treat it as a roadmap.

**Its architecture shipped and survived — under a different name.** The plan/apply split, the three primitives (`create_entity` / `assert_claim` / `retract_claim`), claim-controlled entity lifecycle (`EntityStatus` / `LifecycleStatusModel` in `core/models/mixins.py`), and the DB-level constraints are all live. They were relocated out of the doc's `catalog/ingestion/` into the dedicated **`apps/claim_ingest`** app (`apply/`, `patches/`, `plan.py`), which is what `make ingest-patches` runs. See [DataPatches.md](/docs/DataPatches.md) and [Data.md](/docs/Data.md).

**Its remaining roadmap is moot.** The baseline seed bulk-ingest system this doc was largely about is gone — it did its job and was removed. Fresh dev DBs now come from a Django dump of prod, and catalog data enters exclusively through [data patches](/docs/DataPatches.md). Consequently:

- **Phase 5 (convert the IPDB/OPDB/Fandom/Wikidata/pindata source adapters)** no longer applies — external sources don't ingest directly at all; `catalog/ingestion/` and the per-source `ingest_*` commands were deleted. External data is now upstream of the [flippatch](https://github.com/deanmoses/flippatch) repo.
- **Phase 6 (per-source model/field permission enforcement)** was deferred and is now a different problem (patch authoring/review, not apply-layer gating).
- **Phase 7 (trim `validate_catalog`, wire relationship validation into `assert_claim()`)** — the `validate_catalog` trim is moot (that command was deleted). The single-claim path is _not_ gone, just renamed and relocated: it's now `_assert_claim` in `provenance/claim_writer.py`, the enforced mint chokepoint (see [Actors.md](Actors.md)). It shape-validates relationship claims (`validate_single_relationship_claim`) but still leaves relationship target-_existence_ checks to upstream callers — the exact gap this doc flagged. The doc's own triage stands: not worth closing, because every caller pre-validates targets upstream. Live code, settled question — not deleted.

**Posture note.** This doc's "the DB will be reset to `0001`, so no backfill is needed" assumption was true for its pre-launch era, not abandoned. The world moved to "fresh dev DB = prod Django dump," which is why [Actors.md](Actors.md)'s careful backfill migrations are the live reality. The two docs describe two eras.

---

## The Problem

This project's catalog truth is claims-based: sources and users assert claims, claim resolution picks winners, and resolved model tables materialise the current catalog state. That architecture is sound in principle, but it was not designed as one coherent system from the beginning. Provenance, validation, entity lifecycle, and ingest were added incrementally, and the result is that correctness depends on _how_ data enters the system rather than being enforced uniformly at the claims boundary.

Three areas need to be addressed together:

### Claims system gaps

**Entity existence has no provenance.** Entity creation is a direct ORM write. Once a row exists, there is no claims-based mechanism to mark it as invalid, remove it, or record that it's a duplicate. A source asserting "this machine exists" should be no different from asserting "this machine's year is 1992" — both are facts attributed to a source, and both should be disputable.

**No retraction mechanism.** There is no explicit way to retract a claim or mark an entity as deleted through the claims system. The current relationship sweep machinery infers retraction from omission, but the project currently rebuilds from a bare DB each time, so sweep is effectively a no-op.

**Relationship claims use slugs as identity. ✓ (resolved)** Relationship claims previously stored target entity slugs in their value dicts (e.g. `{"person_slug": "pat-lawlor"}`). Phase 4 migrated all relationship claims to store PKs (e.g. `{"person": 42, "role": 5}`), with slug-to-PK resolution happening at the boundary (API layer, ingest adapters) rather than at materialisation time.

### Validation gaps

Prior work ([ValidationFix.md](ValidationFix.md)) established claim-boundary validation (`validate_claim_value()`, `validate_claims_batch()`, `classify_claim()`) and audited model field validators. That work is complete for scalar and FK claims. The remaining gaps are:

**Resolver and audit carry too much burden.** The resolver has defensive coercions that compensate for upstream validation inconsistencies. `validate_catalog` carries correctness checks that should have been enforced at the claim boundary. Both should be reviewed and trimmed after the ingest redesign, when it's clear which guard rails are still reachable.

**`assert_claim()` lacks relationship target validation.** The bulk path (`bulk_assert_claims`) validates relationship targets. The single-claim path (`assert_claim()`) does not. The interactive PATCH path has its own validation upstream, so this is not a correctness hole today, but one-off management commands using `assert_claim()` for relationship claims would bypass the check.

### Ingest layer problems

**Non-atomic execution.** None of the individual ingest commands wrap their `handle()` in `transaction.atomic()`. (`ingest_all` wraps the full pipeline, but individual commands run without protection during development and debugging.) A command that fails after creating entity rows but before finishing claim assertion leaves partial state that is hard to diagnose and may not be safe to retry.

**Direct writes bypass claims.** Despite the project rule that all catalog fields are claims-based, ingest still has multiple direct-write paths: `QuerySet.update()` for title slugs, `save(update_fields=...)` for wikidata IDs (which are also asserted as claims — a dual-write), direct `opdb_id` rewrites in changelog processing, and `ManufacturerResolver.resolve_or_create()` which creates `Manufacturer` rows with no claim provenance at all.

**Snowflake claim collection.** The same conceptual operations (match or create entities, collect scalar claims, gate slug claims on source attribution, assert relationship claims with sweep) are reimplemented with different variable names, data structures, parameter conventions, and control flow in each command. During the slug migration, this caused an agent to assert slug claims for entities a source didn't create, a human reviewer to miss the same error for two entity types, and a tuple-arity change to break an unpack site that couldn't be found by grep.

**Implicit policy.** Whether a source should assert a slug claim, whether it should assert a name claim, whether it is authoritative enough to sweep, which anomalies are warnings vs. blocking errors — all of these are encoded as if-branches and local conventions rather than as named, auditable policy.

## Design Principles

**Separate planning from application.** Parsing, matching, and claim-intent decisions should happen before any database mutation. Database mutation should happen in one place, in one transaction, with no source-specific logic.

**Additive-only ingest.** The project is pre-launch. The normal workflow is to delete the database and rebuild from scratch. Ingest is a positive assertion process: sources assert what they currently provide. Absence from a source payload has no deletion semantics. The system does not infer what a source has deleted from what it didn't include.

**Explicit operations only.** The system has three primitive write operations: `create_entity`, `assert_claim`, `retract_claim`. These are intentionally narrow and explicit. `create_entity` carries the field values needed to satisfy DB constraints (slug, name, non-nullable FKs); the planner must also emit matching `assert_claim` operations for every claim-controlled field it populates, including `status=active`. The apply layer validates that these pairs are present and consistent — the row values are bootstrapping, the claims are the source of truth. There is no omission-based retraction — if a claim needs to be retracted, the planner emits an explicit `retract_claim` operation. Retraction is available from day one as a primitive (entity lifecycle needs it), but near-term ingest adapters will rarely use it.

**One write path.** Every catalog fact enters the system through claims. No direct ORM writes to claim-controlled fields. Entity creation and claim persistence both happen in the apply layer's transaction — the planner never writes to the database.

**Claims reference entities by PK, not slug.** Relationship claims (credits, themes, gameplay features, etc.) reference their target entities by primary key, not by slug. The planner resolves "IPDB says person Pat Lawlor" to a PK during reconciliation; the claim stores the PK. This eliminates the class of bugs where slug renames invalidate existing claim values, and decouples the claims system from editorial slug choices. Only pindata uses slugs as identity; no external source has slugs.

**Validation at every layer.** Field validators run at the claim boundary (Python-level, clean error messages). `CheckConstraint` enforces the same rules at the database level (safety net for any write path that bypasses Python). Both reference the same constants so they can't drift.

**Source-specific complexity stays source-specific.** Parsing, matching heuristics, encoding fixes, entity-creation decisions (e.g. IPDB's corporate entity derivation) — these are inherently per-source. The architecture should not try to force them into a shared abstraction. It should give them a clear place to live and keep them out of the apply layer.

**Idempotency.** Running the same ingest with the same input data twice should produce identical database state. No new rows, no side effects. The current `bulk_assert_claims` already achieves this (unchanged claims are detected and skipped). This must remain true in the redesign; it is an explicit design goal, not an emergent property.

## Architecture

### Two phases: Plan and Apply

Every ingest run has two phases with an explicit boundary between them.

**Plan** — the source adapter reads raw data, matches it to existing entities, applies source-specific policy, and produces a change plan. The planner does not mutate the database. It references entities that need to be created by including `PlannedEntityCreate` operations in the plan, not by writing rows directly.

**Apply** — the framework creates planned entities (capturing PKs), patches PKs into associated claims, validates planned claims, persists all changes in one transaction, resolves affected entities, and emits a run report. The applier processes explicit operations (`create_entity`, `assert_claim`, `retract_claim`) and contains no source-specific logic.

This separation is the core of the design. Everything else follows from it. The boundary must be strict: the planner produces data, the applier performs writes. If the planner is allowed to "just create a bootstrap row," the separation unravels — dry-run is no longer side-effect-free, and the transaction boundary leaks.

### Source adapters

Each source implements three concerns:

**Parse.** Load raw data, convert to typed source records. This is already extracted into per-source record types (`IpdbRecord`, `OpdbRecord`, etc.) and mostly works well today.

**Reconcile.** Match source records to existing entities. Output is a list of `MatchResult` objects:

```python
@dataclass
class MatchResult[R]:
    entity: Model | None   # existing entity, or None if new
    record: R              # typed source record
    created_by_source: bool
    # possibly: match_type (exact_id, name, heuristic, ambiguous)
```

Reconciliation is a source adapter responsibility, not a framework feature. Shared utility functions handle the common matching strategies:

- `match_by_external_id(queryset, field_name, value)` — look up by source-specific ID (e.g. `ipdb_id`, `opdb_id`, `fandom_page_id`). Strongest match — means the entity has been linked to this source before.
- `match_by_exact_name(queryset, name)` — exact name match
- `match_by_alias(queryset, name)` — exact alias match
- `reconcile_by_id_name_alias(model_class, external_id_field, external_id, name)` — convenience function that calls all three in order, returning the matched entity or None

Source adapters call whichever combination makes sense. Most will use `reconcile_by_id_name_alias`. Adapters that need something different (Wikidata's cross-model chain with normalized name matching, Person disambiguation logic) write their own matching and can use the individual utilities as building blocks.

Name and alias matching carry false-positive risk for entity types with non-unique names (especially Person). Adapters for those types should add disambiguation checks or limit matching to external ID only rather than risk a bad merge — particularly since relationship claims store the matched entity's PK directly, making a false match hard to undo.

Only pindata (the this project editorial export) uses slugs as identity. No external source has slugs. Slugs are editorial/display properties, not cross-source identity.

For new entities (no match found), the reconciler does not create database rows. Instead, the claim collection step emits a `PlannedEntityCreate` alongside the claims for that entity. Claims reference the planned entity by a temporary handle (e.g. an index into the plan's create list, or the source-specific identity values). The apply layer creates the row, captures the PK, and patches it into the associated claims before persisting them.

This is more machinery than "just create the row in the reconciler," but it is what makes the planner genuinely non-mutating. Without it, dry-run would still write rows, the transaction boundary would leak, and the plan/apply separation would be nominal rather than real.

The reconciliation chain must produce structured output rather than silently falling through into row creation as a side effect of a lookup helper.

**Collect claims.** Given reconciled results, produce the set of claims this source wants to assert. Source-specific policy is explicit here:

- Slug gating: assert only when `created_by_source` (cross-source invariant)
- Name policy: per-source, per-entity (IPDB skips name for matched machine models due to encoding corruption; Fandom always asserts name to prevent resolver blanking; OPDB asserts name unconditionally)
- Field mappings: which source fields become which claim field names
- Encoding transforms: HTML entity decoding, mojibake handling
- Relationship claims: credits, themes, gameplay features, etc.

Simple policy (slug gating, source permission declarations) should be data. Complex policy (IPDB's CE derivation from manufacturer data, Fandom's near-duplicate person detection) will remain procedural code. The goal is not to make all policy declarative — it is to give policy a named, auditable location rather than embedding it in general-purpose control flow.

Claim value validation is not a concern of the source adapter. The apply layer runs `validate_claims_batch()` on all planned claims — the same claim-boundary validation established by [ValidationFix.md](ValidationFix.md) Component B. Source adapters produce claims; the framework validates them.

### Operation primitives

The apply layer processes three primitive operations:

- **`create_entity`** — create a new catalog entity row with the model class and required field values (slug, name, any non-nullable FKs, etc.). The planner must also emit matching `assert_claim` operations for every claim-controlled field populated in `create_entity`, including `status=active`. The apply layer validates that these pairs are present and consistent. The row values satisfy DB constraints; the claims provide provenance. All values are attributed to the source that triggered the creation — whether directly from source data (name), system-derived (slug generated from name), or resolved through reconciliation (FK values). "Who created Medieval Madness?" is answered by looking at the `status=active` claim: the source, changeset, ingest run, and timestamp.
- **`assert_claim`** — record a positive source- or user-attributed fact about an entity (scalar field, relationship, or status)
- **`retract_claim`** — explicitly withdraw a previously active claim

These are intentionally narrow. The apply layer does not infer operations from absence — if a source wants to retract something, the planner must emit an explicit `retract_claim`.

Near-term ingest adapters will almost exclusively use `create_entity` and `assert_claim`. `retract_claim` is available from day one because entity lifecycle operations need it (e.g. asserting `status=deleted` may accompany explicit retraction of the entity's claims), but it is not used for omission-based inference.

### Additive-only ingest (near-term)

The project is pre-launch. The normal workflow is to delete the database and rebuild from scratch by running a full ingest. There is no long-lived incremental sync against production data.

In this context, omission-based retraction (inferring that a missing value should be deleted) would be based on assumptions about future source behavior that have not been validated. The near-term ingest model is therefore additive-only:

- Sources assert what they currently provide
- Absence from a source payload has no deletion semantics
- The system does not infer what a source has deleted

The current relationship sweep machinery (`sweep_field` + `authoritative_scope`) is a form of omission-based retraction. On a bare DB it's a no-op (no prior claims to retract). It will be replaced by explicit operations when source adapters are converted.

### Future reconciliation (deferred)

When the project reaches a stage where incremental re-ingest against a live database is needed, retraction-from-omission becomes a real requirement. At that point, a reconciliation workflow can be added that:

1. Takes an authoritative snapshot from a source for a declared scope
2. Computes the diff against the source's current active claims
3. Emits explicit `assert_claim` and `retract_claim` operations
4. Hands those operations to the same apply layer

This is additive to the architecture — it's a planner-level utility that compiles snapshot semantics down to explicit primitives. The apply layer itself never needs to know about sync modes, authoritative scope, or omission semantics.

**Constraint for future reconciliation design:** a claim rejected by validation during the current run must not produce a `retract_claim`. "Source included this field but validation rejected it" is different from "source did not include this field." This rule lives in the reconciliation utility, not in the apply layer.

### Source permissions are separate from retraction

A source may be disallowed from asserting a category of facts regardless of retraction policy. For example, OPDB should not assert `title` or `variant_of` claims; manufacturer/company facts should target `CorporateEntity` not `Manufacturer`. These are source-permission and domain-ownership rules, not sync-mode rules. The framework keeps them separate — source permissions answer "may this source assert claims in this category?" while operations answer "what claims is the source asserting or retracting?"

### Ingest runs and change sets ✓ (data models implemented)

Ingest provenance is recorded at two levels:

**IngestRun** — one record per source invocation. The run-level audit trail: which source, when, what input, whether it succeeded, and structured counts. See `provenance/models/ingest_run.py`.

**ChangeSet** — one per target entity touched in a run. Groups all claims the source asserted about that entity into a coherent unit. Exactly one of user or ingest_run must be set (strict XOR). Retractions are linked to the ChangeSet via `retracted_by_changeset` so entity history shows the complete picture. See `provenance/models/changeset.py`.

"Per target entity" means grouped by the object the claims are about, not by the source record that triggered them. When IPDB processes one machine record, it may touch a MachineModel, a CorporateEntity, and several Persons — that's three ChangeSets. This is the right granularity because entity history is viewed per entity.

Two natural query levels:

- "Show me everything IPDB said about Medieval Madness in this run" — that's the ChangeSet
- "Show me everything that happened in the March 28 IPDB run" — that's the IngestRun

**Visibility.** IngestRun is admin-level. Regular users see entity history through ChangeSets, not run records.

### Apply layer

The apply layer is source-agnostic. It processes the three primitive operations (`create_entity`, `assert_claim`, `retract_claim`) and contains no source-specific logic.

1. **Validate plan structure** (before IngestRun creation) — check that every `create_entity` has matching `assert_claim` operations for all claim-controlled fields it populated (including `status=active`), that every assertion targets a known handle or existing entity, and that handles are unique. Structural errors are adapter bugs, not data issues — they should not leave audit debris.
2. **Create IngestRun** (before transaction) — record source, start time, input fingerprint, status=`running`
3. **Open transaction:**
   a. **Create entities** — execute `create_entity` operations via `bulk_create`, capture PKs, patch them into associated claims.
   b. **Validate** — run `validate_claims_batch` on all planned `assert_claim` operations (see [ValidationFix.md](ValidationFix.md) Component B). Validation collects ALL errors across the entire batch before failing — this is deliberate, so that a single run surfaces every data quality issue rather than forcing a fix-one-rerun-discover-next cycle. If any claim is invalid, the entire transaction fails after reporting all errors. No partial persistence. This is a deliberate pre-launch choice: the project rebuilds from a bare DB, so the fix is always to correct the source data and re-run. A post-launch system with incremental ingest against live data may need to revisit this in favor of skip-and-warn for non-fatal errors.
   c. **Diff** — compare validated claims against existing active claims from this source (scoped to entities in the plan). Unchanged claims are skipped. Changed claims are superseded (old deactivated, new created).
   d. **Persist assertions** — deactivate superseded claims, then bulk-create a ChangeSet per target entity, then bulk-create new Claim rows linked to their ChangeSet. Superseded claims must be deactivated _before_ new claims are inserted — the unique constraint `(content_type, object_id, source, claim_key) WHERE is_active=True` would otherwise reject the insert. ChangeSet creation must be batched (`bulk_create`), not one `create()` per entity in a loop.
   e. **Persist retractions** — for any `retract_claim` operations, deactivate the targeted claims (set `is_active=False` and `retracted_by_changeset` to the entity's ChangeSet)
   f. **Resolve** — materialise affected entities (same resolution layer as today)
4. **Finalise IngestRun** (after transaction) — update counts, status, end time

The IngestRun record is created and updated **outside** the apply transaction. If the transaction rolls back on failure, the IngestRun still survives with status=`failed` and error details — which is exactly when you most want the audit record. ChangeSets and claims are created **inside** the transaction, so partial ingest state never persists on failure.

Source adapters never open transactions or write to the database. The data models (IngestRun, ChangeSet.ingest_run FK, Claim.retracted_by_changeset FK) are implemented. The database will be deleted and migrations reset to `0001` as part of the remaining work, so no backfill or data migration is needed.

### Run reports

The IngestRun record is the persisted form of the run report. In dry-run mode the same report is produced as an in-memory data structure but not written to the database. Either way, the report should make it possible to answer "what happened?", "what changed?", "what was skipped?", and "what needs human curation?" without reading logs or re-running the import.

### Dry run

Because the planner is fully non-mutating, dry run is straightforward: parse, reconcile, collect claims, validate, emit report, apply nothing. No rollback transactions needed. The plan is the same object whether or not it gets applied.

### Testing

The most valuable tests target the plan boundary: given these source records and this database state, what change plan is produced? This directly exposes source-attribution decisions, claim-intent policy, and source permission enforcement without requiring end-to-end command execution. Integration tests still matter but sit on top of a more inspectable model.

### Domain ownership enforcement

The architecture cannot decide which model owns a fact — that is a domain decision humans make. But it can make that decision **enforceable** once made.

Today nothing prevents a source adapter from attaching company facts to `Manufacturer` instead of `CorporateEntity`. That's how the Fandom and Wikidata TODOs happened: both sources target `Manufacturer` for company metadata that should live on `CorporateEntity`, and nothing in the system caught or prevented it.

Source policy declarations should include which models and fields a source is permitted to assert claims against. The apply layer can then reject claims that target a model/field combination the source hasn't declared. This turns "emit claims against the right model" from a convention that source authors must remember into a constraint the framework enforces.

The architecture does not decide that company metadata belongs on `CorporateEntity` rather than `Manufacturer`. It makes that decision — once made — hard to violate accidentally.

## `ingest_pindata` is a special case

The plan/apply model fits IPDB, OPDB, Fandom, and Wikidata naturally. Each is an external source that focuses on one or two entity types per run. `ingest_pindata` is fundamentally different.

`ingest_pindata` is the editorial source that seeds the entire catalog. It processes 12 entity types in dependency order (taxonomy, themes, gameplay features, manufacturers, corporate entities, systems, people, series, titles, models), each with its own matching logic, claim shapes, and resolution steps. Later phases depend on rows created by earlier phases (e.g. titles reference manufacturers and systems that were ingested in prior phases).

This does not fit cleanly into "one source adapter produces one plan, the apply layer executes it."

The right approach is a **compound plan**: the pindata adapter produces a plan with ordered sub-plans, one per entity type (or logical group). The apply layer executes them sequentially within one transaction, making each sub-plan's entities available to the next.

This is the only option that preserves full atomicity naturally — if any phase fails, the entire pindata ingest rolls back. The alternatives (multiple independent plan/apply cycles, or a hybrid that applies each phase independently) reintroduce the non-atomicity problem unless wrapped in an outer transaction, which negates the benefit of separate cycles.

The compound plan also maps most closely to the current phase structure, making migration straightforward: each `_ingest_*` method becomes a sub-plan builder rather than an imperative mutate-as-you-go method. The apply layer handles entity creation, claim persistence, and resolution for each sub-plan in sequence. Each sub-plan must not have direct ORM writes to claim-controlled fields, and entity creation must be explicit and provenance-backed.

## Entity lifecycle

In the current system, entity creation is a direct ORM write with no provenance. Once a row exists, there is no claims-based mechanism to mark it as invalid, remove it, or record that it's a duplicate. Entity existence is ground truth that can't be disputed through the same system that manages everything else.

This is wrong. A source asserting "this machine exists" is no different from a source asserting "this machine's year is 1992" — both are facts attributed to a source, and both should be disputable.

### Entity status as a claim-controlled field

Current catalog record lifecycle policy lives in [Record Lifecycle](../../RecordLifecycle.md#record-lifecycle).

Every catalog entity gets a `status` field with two values:

- **`active`** — the entity is live in the catalog (default)
- **`deleted`** — the entity should not exist (data entry error, bad ingest, malicious actor)

`status` is claim-controlled like any other catalog field. Resolution picks the winner by source priority. An editorial claim (priority 300) asserting `status=deleted` overrides any external source's `status=active`.

Every entity gets a `status=active` claim at creation time — the planner explicitly emits it alongside `create_entity`, and the apply layer validates that the pair is always present. This means every entity has creation provenance from birth: who created it, when, and as part of which ingest run or user action.

**When no status claim remains** (e.g. after actor revocation retracts all claims including `status=active`), status resolves to null. Catalog queries filter on `status='active'`, so a null-status entity is automatically excluded from the live catalog. It surfaces in an admin review queue of entities with no active status claim. An admin can then re-assert `status=active` (if other sources confirm the entity) or assert `status=deleted` (if the entity was fabricated).

### Duplicate handling (deferred)

Duplicate detection (`status=duplicate`, `duplicate_of` relationship claim) will be addressed in a follow-up when there is an actual workflow that produces duplicates. Adding `duplicate` as a status choice without the `duplicate_of` FK and a UI/ingest workflow to drive it would be a half-implemented feature. The status field is trivially extensible — adding a new choice and the supporting FK later costs nothing, especially since the DB is being reset to `0001`.

The design intent is unchanged: `duplicate_of` will follow the `variant_of` pattern (self-referential FK, relationship claim), and claims on duplicates will stay as historical record rather than moving to the canonical entity.

### Soft delete

Entity rows are never hard-deleted. A `status=deleted` entity remains in the database with all its claims intact. The provenance trail records who marked it, when, and why (via the claim's citation and changeset). Catalog queries filter on `status=active` to exclude inactive entities from the live catalog.

This also supports restoration — if a deletion was wrong, re-asserting `status=active` with sufficient priority reverses it through normal claim resolution.

### Scenarios

**Data entry error / bad ingest.** A user asserts `status=deleted` with a citation explaining why. The entity disappears from the active catalog but its history survives.

**Actor revocation.** All claims from a bad actor are retracted. Entities they created that have since been confirmed by other sources retain their `status=active` claim from those other sources and survive. Entities with no remaining `status=active` claim from any source surface for review.

## Database-level validation ✓ (implemented)

Python validators on model fields (`MinValueValidator`, `MaxValueValidator`, `RegexValidator`, `validate_no_mojibake`) run at the claim boundary via `validate_claim_value()` and during form/API input. But they are invisible to the database. Any write path that bypasses Python validation — `bulk_create()`, `QuerySet.update()`, `save()` without `full_clean()`, the resolver's `save(update_fields=...)` — can persist invalid data. The apply layer's fail-fast validation is the primary defense, but DB constraints are the safety net beneath it.

### Approach: shared constants referenced by both validators and constraints

Range limits are defined once as constants on each model class and referenced by both the field validator and a `CheckConstraint`:

```python
class MachineModel(TimeStampedModel):
    YEAR_MIN, YEAR_MAX = 1800, 2100

    year = models.IntegerField(null=True, blank=True,
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)])

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(year__gte=YEAR_MIN, year__lte=YEAR_MAX)
                         | Q(year__isnull=True),
                name="machinemodel_year_range",
            ),
        ]
```

This eliminates drift between the two layers — both reference the same constant. `get_field_constraints()` (which introspects field validators to serve min/max hints to the frontend) and `validate_claim_value()` (which runs the validator chain at the claim boundary) continue to work unchanged.

### Introspection complication

Replacing validators with constraints (rather than adding constraints alongside them) would break two runtime systems:

- `get_field_constraints()` reads `field._validators` to extract min/max for frontend form hints
- `validate_claim_value()` iterates `field.validators` to run the validation chain at claim time

Django's `CheckConstraint` conditions (`Q` objects) are not designed for introspection — parsing them to extract range limits is fragile. The shared-constants approach avoids this entirely: validators stay on the fields, constraints are added alongside them, and both reference the same source of truth.

### Phasing

**Phase 1: Cross-field invariants and non-blank constraints. ✓** These have zero enforcement today — not even Python-level. Purely additive `CheckConstraint` additions, each with a human-readable `violation_error_message`:

- `CorporateEntity`: `year_start <= year_end` (when both non-null)
- `Person`: `birth_year <= death_year` (when both non-null)
- `Person`: `birth_month` requires `birth_year`; `birth_day` requires `birth_month` (and same for death fields)
- `MachineModel`: `month` requires `year`
- Non-blank `CheckConstraint` on `name` for all catalog entities with `blank=False`

Wire `validate_constraints()` into the resolver (before `save()`) and the apply layer (before entity persistence) so cross-field violations produce clean `ValidationError` responses, not raw `IntegrityError`.

**Cross-field validation:** `validate_claim_value()` validates one claim at a time and can't check relationships between fields. But Django's `Model.validate_constraints()` evaluates `CheckConstraint` conditions against the instance's current field values in Python. After resolution applies winning claim values to the model instance (but before `save()`), calling `instance.validate_constraints()` catches cross-field violations and raises `ValidationError` with the constraint's `violation_error_message` — clean 422 response, no raw `IntegrityError`. The constraint is defined once on the model and serves as both the DB-level backstop and the Python-level check. Each `CheckConstraint` should include a human-readable `violation_error_message` (e.g. "birth_year must be <= death_year").

**Phase 2: Range constants + CheckConstraints. ✓** The systematic work:

1. Define range constants on each model class
2. Reference constants in existing validators (update `MinValueValidator(1800)` to `MinValueValidator(YEAR_MIN)`)
3. Add `CheckConstraint` for each range using the same constants
4. Add a drift-detection test that asserts validator limits match constraint conditions

Phase 3 (mechanical cleanup) is also complete:

1. Migrate `unique_together` to `UniqueConstraint` (6 models)
2. Add `db_default=Now()` on `created_at` fields only. `updated_at` stays Python-managed (`auto_now`) — true DB-managed update timestamps would require triggers, which is a separate concern. Verify during implementation that `db_default=Now()` alongside `auto_now_add=True` is accepted by `makemigrations` — the intent is correct (Python default for ORM inserts, DB default for non-ORM inserts) but the combination should be tested.
3. Add `db_default` on fields with meaningful defaults (e.g. `IngestRun.status`)
4. ~~Regex `CheckConstraint` for `wikidata_id` fields~~ — dropped. SQLite (the dev database) does not support regex in `CHECK` constraints, and conditional migration machinery for one field on two models isn't worth the complexity. The Python `RegexValidator` on the field is sufficient — it runs at the claim boundary via `validate_claim_value()`.

The database is being deleted and migrations reset to `0001`, so all constraints can be declared directly on the models with no data migration.

## What This Does Not Solve

**Domain modeling decisions.** The architecture enforces domain ownership but does not decide it. Which model owns which facts is a domain decision that must be made separately. The existing Fandom and Wikidata TODOs (targeting `Manufacturer` when they should target `CorporateEntity`) are domain fixes that the architecture would then enforce.

**Source-specific parsing complexity.** IPDB's gameplay feature extraction with multiball special-casing, Fandom's wiki fetching and near-duplicate detection, IPDB's encoding corruption handling — these are essential complexity that no architecture can remove. The architecture gives them a clear home (the source adapter) and keeps them out of the apply layer, but they remain code that must be written and maintained per source.

## What Stays Source-Specific

- Parsing raw data into typed records
- Reconciliation strategy (which utility functions to use, in what order, with what disambiguation)
- Field mappings
- Name and encoding policy
- Entity creation decisions
- Complex claim-intent policy that cannot be expressed as data

## What Stops Being Source-Specific

- Transaction management
- Shared reconciliation utilities (match by external ID, exact name, alias)
- Claim persistence and retraction
- Resolution orchestration
- Run reporting
- The "collect into a list, then bulk_assert, then resolve" boilerplate that every command currently reimplements

## Prior work

[ValidationFix.md](ValidationFix.md) established the claim boundary as the place where validation happens and built the machinery this plan reuses:

- `validate_claim_value()` — per-field validation using Django's field validator chain
- `validate_claims_batch()` — batch validation with structural claim classification
- `classify_claim()` — structural classifier (DIRECT, RELATIONSHIP, EXTRA, UNRECOGNIZED)
- `validate_fk_claims_batch()` — batched FK target existence checks
- `validate_relationship_claims_batch()` — batched relationship target existence checks
- Field validator audit — catalog model fields now carry adequate validators (range checks, format validators, mojibake checks)

The apply layer calls `validate_claims_batch()` on all planned claims. It does not replace or duplicate the validation machinery.

DB-level validation (~84 `CheckConstraint` additions) established the database as a safety net beneath claim-boundary validation:

- `field_not_blank()` helper + 36 non-blank constraints on `name`/`value` fields
- Module-level range constants referenced by both field validators and `CheckConstraint` (20 range constraints), with a drift-detection meta-test
- Cross-field invariants: year ordering, month-requires-year, date component chains (10 constraints)
- Self-referential anti-cycle: `variant_of`/`converted_from`/`remake_of`/`parent` != pk (4 constraints)
- `unique_together` migrated to `UniqueConstraint` (6 models), `db_default` additions
- `validate_check_constraints()` in the resolver filters to cross-field constraints only (via `violation_error_code`), because the resolver legitimately resets unclaimed fields to defaults like `""`

[IngestRefactor.md](IngestRefactor.md) contains the earlier iteration of the ingest architecture design, including analysis of snowflake patterns and the original sync modes proposal. This document supersedes it.

Remaining validation work (trimming `validate_catalog`, reviewing resolver guard rails, wiring relationship target validation into `assert_claim()`) is tracked in Phase 7 below.

## Implementation Phases

### Phase 1: Apply layer framework ✓ (implemented)

Build the source-agnostic engine that takes a plan and executes it. Data types (`PlannedEntityCreate`, `PlannedClaimAssert`, `PlannedClaimRetract`, `IngestPlan`, `RunReport`), the `apply_plan()` function, and tests with synthetic plans. No source adapter conversion.

Delivers: the three primitives (`create_entity`, `assert_claim`, `retract_claim`) working end-to-end with transaction management, ChangeSet batching, idempotent diff, fail-fast validation, dry run, and IngestRun audit trail.

Implemented in `catalog/ingestion/apply.py` with 19 tests in `catalog/tests/test_apply.py`. Includes `handle_refs` for cross-entity FK dependency resolution during entity creation.

### Phase 2: First source adapter (OPDB) ✓ (implemented)

Convert `ingest_opdb` from imperative command to plan/apply. OPDB is the simplest external source (single entity type, no entity creation, straightforward field mappings). Proves the framework works with real data.

Implemented in `catalog/ingestion/opdb/adapter.py` with `build_opdb_plan()` + `parse_opdb_records()`. Management command calls `build_opdb_plan()` → `apply_plan()`. Tests in `catalog/tests/test_opdb_adapter.py` validate plan output at the boundary.

### Phase 3: Entity lifecycle (`status` field) ✓ (implemented)

Add claim-controlled `status` field (`active`, `deleted`) to all catalog entities. Wire `status=active` assertion into `create_entity` consistency check. Filter catalog queries on `status='active'`. Duplicate handling (`status=duplicate`, `duplicate_of` relationship claim) deferred to a follow-up.

Implemented via `LifecycleStatusModel` in `core/models.py` with `EntityStatus` enum (`active`, `deleted`), `status_valid()` DB constraint, and null allowed for entities with no remaining status claim.

### Phase 4: Relationship claim PK migration ✓ (implemented)

Changed relationship claims from slug-based identity (`person_slug`, `theme_slug`) to PK-based identity (`person`, `theme`). Value dict keys dropped the `_slug` suffix — keys now match identity keys (e.g. `{"person": 42, "role": 5}`). Claim keys use PKs (`credit:person=42:role=5`). Location claims migrated from materialized path to PK.

Updated: `RELATIONSHIP_SCHEMAS` and validation registry in `claims.py`, `validate_relationship_claims_batch` in `validation.py`, all resolvers in `resolve/_relationships.py` (removed slug→PK lookup dicts — claims carry PKs directly), API planning layer in `edit_claims.py` (slug→PK resolution at API boundary), OPDB adapter, all four legacy ingest commands, `validate_catalog.py` audit functions, and ~12 test files.

Legacy ingest commands now build PK-based claims but remain imperative (full plan/apply conversion is Phase 5).

### Phase 5: Remaining source adapters

Convert `ingest_ipdb`, `ingest_fandom`, `ingest_wikidata`, `ingest_pindata` (compound plan). Each adapter: parse, reconcile, collect claims, produce plan. Remove old imperative commands. Note: legacy commands already build PK-based claims (Phase 4), so the conversion is purely structural (plan/apply separation), not a claim format change.

**✅ `ingest_ipdb` converted.** Adapter in `catalog/ingestion/ipdb/adapter.py`, feature extraction in `catalog/ingestion/ipdb/features.py`, management command slimmed to ~70 lines. Creates 4 entity types (CorporateEntity, MachineModel, Person, Theme). Uses `identity_refs` for deferred credit/theme relationship claims where Person/Theme entities are created in the same plan. Deliberate behavior changes: sweep dropped (additive-only), dead manufacturer claim on MachineModel replaced with informational extra_data claims, manufacturers must pre-exist, location validation skipped for new CEs.

`ingest_pindata` is last (compound plan, most complex). The current `apply_plan` takes one flat plan. `ingest_pindata` needs ordered sub-plans where each phase's created entities are available to the next phase's claims (e.g. titles reference manufacturers created in an earlier phase). This will require either a `list[IngestPlan]` variant that loops inside one transaction, or extending `IngestPlan` to carry ordered sub-plans. Design this when converting `ingest_pindata`, not before — the simpler adapters don't need it.

### Phase 6: Source permission enforcement (deferred)

Add per-source model/field permission declarations. The apply layer rejects claims targeting disallowed combinations. Deferred: the two active ingest sources (IPDB, OPDB) are converted and working correctly, and adapter correctness is adequately covered by code review and plan-boundary tests. Revisit if/when third-party or community-contributed adapters become a concern.

### Phase 7: Cleanup (deferred)

Trim `validate_catalog` checks redundant with claim boundary validation and DB-level constraints. Triaged: 4 checks are fully redundant (`check_nameless_models/titles/persons` duplicated by `field_not_blank` CheckConstraints, `check_self_referential_variant` duplicated by DB anti-cycle constraints); the other 14 checks remain valuable for data quality, integrity, and regression testing. Resolver defensive coercions are mostly justified (type coercions handle legitimate JSON variance). Relationship validation in `assert_claim()` is not needed — all callers pre-validate targets upstream. Low priority; defer until there's a reason to touch these files.

## Non-Goals

This document defines the target architecture. It does not:

- Define every dataclass or module in final detail
- Choose a storage format for planned entity identities or run metadata
- Decide exact package layout beyond the architectural split into source adapters and apply layer

## Acceptance Criteria

This plan is successful when:

- ✅ The claims system has three explicit primitive operations: `create_entity`, `assert_claim`, `retract_claim`
- ✅ Entity existence is provenance-backed via a claim-controlled `status` field (`active`, `deleted`)
- ✅ Entity rows are never hard-deleted; catalog queries filter on `status=active`
- ✅ Relationship claims reference target entities by PK, not by slug
- All catalog facts enter the system through claims — no direct ORM writes to claim-controlled fields (OPDB, IPDB done; Fandom, Wikidata, pindata remain)
- ✅ Every ingest run is recorded as an IngestRun with structured run metadata
- ✅ Every entity touched in an ingest run has a ChangeSet grouping its claims
- ✅ Retractions are linked to ChangeSets via `retracted_by_changeset`
- ✅ The apply layer is source-agnostic — it processes explicit operations with no source-specific logic
- ✅ The planner is non-mutating — dry run produces a report without writing to the database
- ✅ Running the same ingest twice produces identical database state (idempotency)
- Source adapters replace the current imperative ingest commands (OPDB, IPDB done; Fandom, Wikidata, pindata remain)
- `validate_catalog` and resolver guard rails have been reviewed and trimmed post-redesign
- `assert_claim()` validates relationship targets
- ✅ Range limits are defined as shared constants referenced by both field validators and `CheckConstraint`
- ✅ Cross-field invariants (year ordering, month-requires-year) are enforced at the DB level
- ✅ Non-blank constraints exist for all `name` fields
- ✅ `unique_together` migrated to `UniqueConstraint`

## Follow-Ups

Items identified during implementation that are not blocking but worth tracking.

### Plan-aware dry-run validation

Dry-run currently skips deferred relationship claims (`identity_refs`) entirely because the relationship validation layer checks that referenced PKs exist in the DB, and planned entities don't exist yet. A proper fix would make dry-run validate deferred relationships against `plan.entities` + DB, so plan-local entities are treated as existing for validation purposes. This benefits all adapters and would close the gap where adapter mistakes in deferred relationship construction pass `--dry-run` but fail on real runs.

### Full IPDB ingest verification against real data

The IPDB adapter tests use a 4-record sample fixture. A manual `make pull-ingest && python manage.py ingest_ipdb` against the full IPDB dataset should be run before merging to confirm no regressions at scale.

### OPDB adapter could adopt identity_refs

OPDB doesn't need `identity_refs` today (it only creates MachineModels — all entities referenced in relationship claim values are pre-existing). If a future OPDB change creates entities that are also referenced in relationship claims, the primitive is ready.
