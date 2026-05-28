# Mypy Fixing

## Context

We recently introduced mypy and grandfathered in a lot of exceptions in backend/mypy-baseline.txt. This is the plan to attack them.

## Status

Mostly DONE. Steps 1–11 complete. Step 12 and Step 7.1 remain open.

## Running mypy

- **Full check:** `./scripts/mypy` from the repo root. Wraps `uv run --directory backend mypy --config-file pyproject.toml .` piped through `mypy-baseline filter`. Exit 0 only when no _new_ (above-baseline) errors exist. Reports `fixed / new / unresolved` and a per-error-code breakdown with deltas. Do **not** run `mypy` directly — absolute paths won't match the baseline.
- **Don't pass a file path.** `./scripts/mypy src/foo.py` is ignored by the wrapper on purpose (see the comment at the top of [scripts/mypy](scripts/mypy)); partial runs generate paths that don't align with the baseline.
- **Sync baseline after clearing entries:** `uv run --directory backend mypy --config-file pyproject.toml . 2>&1 | uv run --directory backend mypy-baseline sync`. Only run this once `./scripts/mypy` shows `new: 0`.
- **Kill dmypy when the type system changes.** `scripts/mypy` uses fresh one-shot mypy, but the IDE and `scripts/dmypy` use a persistent daemon. Adding a type alias, changing an override, or renaming a module-level symbol can make dmypy's cache stale and report wrong errors. Fix: `uv run --directory backend dmypy stop` (the IDE pays cold-start cost on next check).
- **Relevant overrides to keep in mind** (from [backend/pyproject.toml](../../../backend/pyproject.toml)):
  - `strict = true` is global. Touching imports in an otherwise-clean file can surface new errors.
  - `*.tests.*` / `conftest` relaxes `disallow_untyped_defs` + friends ([line 127](../../../backend/pyproject.toml#L127)) — annotation-style rules only, not `arg-type` / `attr-defined` / etc.
  - `apps.*.api.*` relaxes `disallow_untyped_decorators` ([line 136](../../../backend/pyproject.toml#L136)) for Ninja's untyped decorators.

## Guiding principles

- **Type callees before callers.** Most `no-untyped-call` errors evaporate when the function being called gets annotated. Sweeping caller signatures against `Any`-returning helpers just means revisiting them.
- **Ratchet via the baseline, not per-module strictness.** `strict = true` is already global in [backend/pyproject.toml](../../../backend/pyproject.toml); the only per-module levers are _relaxations_, and the enforceable direction is removing them. Concretely: (a) shrink `mypy-baseline.txt` monotonically and fail CI on new entries (`mypy-baseline --fail-on-new-error` or equivalent); (b) as `apps.*.api.*` packages clean up, narrow or remove the `disallow_untyped_decorators = false` relaxation at [pyproject.toml:136](../../../backend/pyproject.toml#L136).
- **Re-run `make codegen` after any Ninja endpoint retyping.** Annotated return types change the generated OpenAPI schema and therefore `frontend/src/lib/api/schema.d.ts`. Run the frontend typecheck too, not just pytest.

## Idioms

### Idiom for serialization helpers: return Schema, not `dict`

In a Django + Ninja app, the Ninja `Schema` (Pydantic v2) is the canonical data shape — for request/response validation _and_ for in-process typing. Serialization helpers should **return Schema instances**, not dicts that later get re-validated against the same Schema.

- **Schema-shaped output → return the Schema instance.** Pydantic v2 construction is microseconds; the "runtime cost" concern is not real.
- **No Schema exists yet for this shape → add one.** Two duplicated shapes (a TypedDict and a Schema) is a worse outcome than one Schema used everywhere.
- **Truly free-form `JSONField` bags → `JsonData` from [apps/core/types.py](../../../backend/apps/core/types.py).** Only `extra_data` qualifies. `JsonData = Mapping[str, object]` — `object` (not `Any`) forces `isinstance`-narrowing at use sites, which is correct for JSON. `Mapping` (covariant) is needed because dict literals with specific value types aren't subtypes of the invariant `dict[str, object]`. Use `JsonBody` (the `dict` form) only for test-client write bodies.
- **Exception: cached-bytes hot paths.** Endpoints that build the input to `set_cached_response` (e.g. `list_all_titles`, `list_all_models`) persist JSON bytes; the dict _is_ the cached form. Building Schemas only to `model_dump()` them back is the round-trip the cache exists to avoid. Keep these few helpers dict-returning, type the local as `list[dict[str, Any]]`, and leave a comment naming the cache contract. The Schema for the same shape still applies to the non-cached sibling endpoint.
  - **Cached-endpoint return type:** `get_cached_response()` returns `HttpResponse | None`, so the endpoint's return annotation must be `HttpResponse | list[dict[str, Any]]` (not just the list). Mixing `return response` (HttpResponse) and `return result` (list) in one function otherwise fails mypy.

`TypedDict` is the fallback for code that can't or won't use Pydantic. In a Ninja app, Pydantic is already present — use it.

**Flipping a serializer's return from `dict` to Schema requires updating every caller's return annotation too.** Endpoint funcs typed `-> dict[str, Any]` that `return _serialize_foo(...)` must flip to `-> FooSchema`. Mypy catches one or two; grep `_serialize_foo` across the package to find the rest in one pass.

### Idiom for `Any`: four categories, only one is valid

Writing `Any` means "don't type-check this." Default to never. When tempted, classify which of these it is:

1. **Lazy `Any`** — "I haven't bothered to write the real type." The real type exists and callers pass exactly it. **Not valid.** Write the real type.
2. **Queryset-annotated attribute** — a single `.annotate()` field (e.g. `title.model_count`) that isn't on the model. Typing the param as `Any` throws away the whole model's type info to paper over one attribute. **Not valid.** Use `getattr(obj, "annotated_field", default)` — scoped to the one field.
3. **Third-party API constraint that forces information loss** — e.g. `Prefetch[str, Any, str]` on a factory feeding `prefetch_related`, which has a single `_PrefetchedQuerySetT` TypeVar that can't unify across heterogeneous concrete args. The `Any` isn't hiding info we have; it acknowledges the 3rd-party API shape discards it. **Valid — with a comment naming the constraint.**
4. **"JSON-shaped" data** — looks like it justifies `Any` but doesn't; JSON's value type is `object` with `isinstance`-narrowing. **Not valid.** Use `JsonData` / `JsonBody`.

Rule: if you're about to write `Any` and it's not #3, find the real type.

### Idioms for introspection-heavy code

For code that operates on a generic `type[Model]` (resolvers, validators, management commands):

- **Use `_default_manager` instead of `.objects`** — typed on the base `Model` class; `.objects` is added per-subclass and invisible at `type[Model]`.
- **Narrow `type[Model] | Literal['self']`** with `assert isinstance(target_model, type) and issubclass(target_model, models.Model)`. At runtime `"self"` is already resolved by `_meta.get_field()`; the union is a django-stubs artifact.
- **Narrow `Field | ForeignObjectRel`** with `isinstance(field, models.Field)`. `ForeignObjectRel` lacks `validators`, `blank`, `to_python`, `choices`.

### Idiom for generics over heterogeneous model classes

When a helper is generic over N concrete model classes that share a Schema shape but _don't_ share a base class carrying the fields / custom manager (e.g. the 9 taxonomy models share `name` / `slug` / `display_order` / `CatalogManager` but inherit them from different mixins):

- **Constrained `TypeVar`, not bound.** A bound TypeVar (`[M: CatalogModel]`) collapses `type[M]` to the common base and loses the per-subclass fields. (As of Step 4, `CatalogModel` now inherits `LifecycleStatusModel`, so `.objects.active()` _is_ available on the common base — the rationale against bound is solely about per-subclass fields like `RewardType.aliases` or `Title.titlemachinemodel_set`.) Only a constraint list preserves the concrete type at each call site.
- **`typing.TypeVar` with a module-level constraint list + per-def `# noqa: UP047`.** PEP 695 inline syntax (`def foo[M: (A, B, C, …)](…)`) is ergonomic for 1–2 constraints but forces the full list to be repeated at every generic function. Module-level `TypeVar` keeps the constraints DRY; ruff's UP047 then fires per def — suppress it locally. **This rationale is specific to constraint lists.** For simple _bounded_ TypeVars (`[M: CatalogModel]`), PEP 695 inline syntax is the right call — it's shorter, matches the project convention ([bulk_create_validated[M: Model]](../../../backend/apps/core/validators.py#L12), [\_agreed_value[T]](../../../backend/apps/catalog/api/titles.py#L379)), and avoids the UP047 suppression entirely. Don't copy the taxonomy pattern to non-constrained call sites.
- **Narrow with `isinstance`, not `hasattr` + `getattr`.** When one arm of the union has a reverse relation the others don't (e.g. only `RewardType` has `aliases`), `if isinstance(obj, RewardType): obj.aliases.all()` type-checks cleanly. The `hasattr` + `getattr(obj, "attr")` spelling trips ruff's B009.
- **The speculative fix is a shared abstract base.** Introducing a `TaxonomyBase` mixin with the shared fields and manager would let a bound TypeVar work and eliminate the noqas. Not in-scope for any step of this plan — revisit only if multiple future helpers need the same shape or the entity-type registry consolidation lands.

### Idiom for Schema/dict boundaries during migration

When a helper transitions from returning `dict` to returning `Schema`, but the converse boundary still returns `dict` — either a shared callback registrar consumed by untyped callers, or a cross-step callee whose own conversion is scheduled later:

- **Wrap at the boundary, not the callee.**
  - Schema-side calling dict-side: `Schema.model_validate(callee_dict(...))` at the call site. (Step 1 titles.py used this for `MachineModelDetailSchema.model_validate(_serialize_model_detail(pm))`, pending Step 3.1's removal of the bridge.)
  - Dict-side calling Schema-side: `serialize_detail=lambda obj: _serialize_taxonomy(obj).model_dump()` confines the round-trip to the single call site.
  - Either way, tightening the shared callback type or callee return ripples into every untyped consumer, ballooning the current step's scope.
- **Flag the wrapper as tech debt.** A comment naming the later step that will remove the bridge keeps the intent visible. Don't silently leave the `.model_dump()` / `.model_validate()` hop in place once the boundary is tightened.

### Idiom for Pydantic response unions: structural discrimination is required

When typing a Ninja response slot as a union of Schemas (`response={422: SchemaA | SchemaB}`), Pydantic smart-mode union dispatch is **structural**, not intent-based. Two schemas that share a required field subset will mis-route bodies in both directions:

- A body with only the shared fields matches whichever arm covers the rest via defaults — so the "minimal" body is serialized as the "rich" schema, with the rich schema's default values leaking into the wire response.
- A body with extra fields matches whichever arm treats extras permissively (the Pydantic default) — so the "rich" body is serialized as the "minimal" schema, **silently dropping the extra fields from the wire response**.

Both failure modes pass mypy, pass OpenAPI generation, and pass tests that don't assert on the full response body. They surface as frontend classifier bugs (wrong `kind` branch) or as lost data in the 422 body.

Two tools make dispatch deterministic; apply both on every union of response schemas with shared fields:

- **Mark the distinguishing field as required (no default) on the richer schema.** A body lacking the field then fails validation against the rich arm, forcing the minimal arm.
- **Set `model_config = ConfigDict(extra="forbid")` on the minimal schema.** A body carrying extras then fails validation against the minimal arm, forcing the rich arm.

Before landing a union, verify dispatch with `TypeAdapter(A | B).validate_python(body)` for every real body shape the endpoint emits. The baseline and test suite will not catch it. `{"detail": "…"}` alone is ambiguous; fix it before shipping.

See [schemas.py:SoftDeleteBlockedSchema](../../../backend/apps/catalog/api/schemas.py) / `AlreadyDeletedSchema` / `PersonSoftDeleteBlockedSchema` for the canonical example (Step 3.2).

### Idiom for narrowing optional FK fields

`obj.fk_id is not None` (column read, no DB hit) and `obj.fk is not None` (related-object dereference, may hit the DB) **are not equivalent**. Don't swap one for the other to satisfy mypy.

- The original guard is usually `obj.fk_id is not None` because callers don't want the related fetch.
- To narrow the related object for mypy without changing semantics, bind a local and assert: `parent = obj.fk; assert parent is not None`. The `_id` check guarantees the assert holds; the local lets mypy track the narrowing through the rest of the block.

## Step 1: keystone helpers in `catalog/api` - DONE

Type the shared helpers before their callers. Expect the `no-untyped-call` count to drop noticeably as a side effect.

- [apps/catalog/api/taxonomy.py](../../../backend/apps/catalog/api/taxonomy.py) — **done** (58 → 2; the 2 remaining are pre-existing `Cannot infer type of lambda` on default-arg-captured lambdas in the `_register_*` wrappers).
- [apps/catalog/api/titles.py](../../../backend/apps/catalog/api/titles.py) — **done** (51 → 0). Two `MachineModelDetailSchema.model_validate(_serialize_model_detail(...))` bridges remain; remove when Step 3.1 converts `_serialize_model_detail` to return the Schema. `_serialize_model_detail` and `_model_detail_qs` in [machine_models.py](../../../backend/apps/catalog/api/machine_models.py) were minimally typed (return `dict[str, Any]` and `QuerySet[MachineModel]`) as cross-file callee unblocks — the full Schema conversion is Step 3.1 work.

Return Schema instances (see idiom above). Add schemas for shapes that don't have one yet.

## Step 2: `catalog/api` signatures - DONE

With taxonomy + titles done, the rest of the package falls into two groups. Order matters: shared-helper modules first (callee-before-caller), then endpoint-only files. Run `make codegen` + frontend typecheck after each batch.

### Step 2.1: shared helper signatures - DONE

(not endpoint files; expose the keystone helpers every endpoint in the package calls — `execute_claims`, `plan_*`, `assert_*`, `serialize_blocking_referrer`, `execute_soft_delete`).

`edit_claims.py` (17 → 0) → `soft_delete.py` (17 → 0) → `entity_create.py` (11 → 0) → `entity_crud.py` (17 → 0).

Typing these first means the step 2.2 sweep collects `no-untyped-call` reductions for free.

### Step 2.2: endpoint signatures - DONE

(`request: HttpRequest`, explicit Schema return types)

`systems.py` (12 → 0) → `manufacturers.py` (11 → 0) → `series.py` (10 → 0) → `locations.py` (20 → 0) → `people.py` (20 → 0) → `machine_models.py` (34 → 0) → `page_endpoints.py` (46 → 0).

`machine_models.py` was sequenced before `page_endpoints.py` for two reasons: (a) it carries the titles.py bridges (`MachineModelDetailSchema.model_validate(_serialize_model_detail(...))`) which Step 3.1 will remove; (b) `page_endpoints.py` imports `_serialize_model_detail` / `_model_detail_qs` from it, so typing machine_models first unblocks the largest file the same way it unblocked titles.

Baseline: 710 → 377 (~47% reduction). Commit: `e7b8204f`.

## Step 3: close out `catalog/api` - DONE

Order: Schema-return conversion (3.1) before error-schema swap (3.2) because 3.1 is unblocked while 3.2 needs a design decision. Step 4 (tech-debt cleanup) is independent and can land any time. Step 5 (decorator-relaxation narrowing) is the final milestone and is gated on Step 3.

### Step 3.1: Convert `_serialize_model_detail` to return Schema - DONE

Step 1's deferred work. Two bridges in [titles.py](../../../backend/apps/catalog/api/titles.py) still read `MachineModelDetailSchema.model_validate(_serialize_model_detail(pm))`; they must be removed, not left to rot. `_serialize_model_detail` is currently typed `-> dict[str, Any]` as a minimal-touch unblock. Flip the return to the Schema, drop the two `model_validate` wrappers in titles.py, and re-run `make codegen` + frontend check.

**Done when:** `_serialize_model_detail` returns `MachineModelDetailSchema`, the two `model_validate` wrappers are gone from titles.py, `./scripts/mypy` stays clean, and frontend typecheck passes.

### Step 3.2: Swap `422` / `404` dict responses to shared error schemas - DONE

Delete endpoints now type 422 as a union of `SoftDeleteBlockedSchema | AlreadyDeletedSchema` (or `PersonSoftDeleteBlockedSchema | AlreadyDeletedSchema` for `delete_person`); restore endpoints use `ErrorDetailSchema` for 422 / 404.

**Design decisions resolved:**

- **Kept two blocked schemas, not one generalized field.** `SoftDeleteBlockedSchema.active_children_count` and `PersonSoftDeleteBlockedSchema.active_credit_count` measure genuinely different things (cascade-owned children vs. Credits referentially joined to active Models/Series). Collapsing to `active_referrer_count` would have unified only the wire field name — the pre-walker query logic is inherently different and not consolidatable, and the generic PROTECT-walker path is already shared via `execute_soft_delete`. A rename would also have touched `PersonDeletePreviewSchema.active_credit_count`, widening the blast radius beyond 422 bodies.
- **Introduced `AlreadyDeletedSchema` as the second union arm.** The "already soft-deleted" 422 has only `detail` (no `blocked_by`), which the frontend's [delete-flow.ts classifier](frontend/src/lib/delete-flow.ts) relies on to fall through to `form_error` instead of `blocked`. A distinct class alone is **not sufficient** — Pydantic smart-union dispatch is structural, so `{"detail": "…"}` matches whichever arm has defaults covering the missing fields, and `{"detail": "…", "blocked_by": […]}` matches whichever arm treats extras permissively. Correct dispatch required making `blocked_by` required (no default) on `SoftDeleteBlockedSchema` / `PersonSoftDeleteBlockedSchema`, **and** `model_config = ConfigDict(extra="forbid")` on `AlreadyDeletedSchema`. See the "Pydantic response unions need structural discrimination" idiom above. Named `AlreadyDeletedSchema` rather than reusing `ErrorDetailSchema` so the union is self-documenting at the call site.
- **No inheritance between error schemas.** Pydantic subclassing doesn't affect union dispatch (structural) or openapi-typescript output (duplicates fields, no TS subtyping). No backend code processes these polymorphically; no frontend code either. Inheritance would be a type-gesture only.

## Step 4: Clean up tech debt from the Step 2 signature sweep - DONE

Quality regressions introduced to clear the baseline quickly. Independent of Steps 3 / 5 — can land any time, but should not normalize.

### Done

- **`_Entity = Any` is wider than its justification.** — **DONE (commit `7c512c09`).** `plan_gameplay_feature_claims` / `plan_credit_claims` now take `entity: MachineModel`; `plan_abbreviation_claims` takes `entity: MachineModel | Title`. `_Entity = Any` is kept only for the genuinely cross-model `plan_parent_claims` / `plan_alias_claims`; comment in [edit_claims.py](../../../backend/apps/catalog/api/edit_claims.py) updated to reflect the narrower scope.
- **`cast(Any, user)` widens past what the runtime guarantees.** — **DONE (commit `7c512c09`).** Both call sites now narrow with `assert not isinstance(user, AnonymousUser)` and use `cast(User, user)` as a localized django-stubs workaround at the `ChangeSet.objects.create(...)` line. The cast is deliberate and flagged with a comment pointing at [docs/plans/UserModel.md](UserModel.md), which captures the follow-up work (introducing a custom User model) that will remove both the cast and the `User` tripwire. `_UserLike` renamed `_RequestUser` and kept wide (`AbstractBaseUser | AnonymousUser`) at public entry points; narrowed internally.
- **`cur: Any` loop-variable pattern.** — **DONE (commit `7c512c09`).** All three spots ([manufacturers.py](../../../backend/apps/catalog/api/manufacturers.py), [machine_models.py](../../../backend/apps/catalog/api/machine_models.py), [locations.py](../../../backend/apps/catalog/api/locations.py)) now use `cur: Location | None = cel.location`.
- **`list[Any]` return on `list_manufacturers` / `list_people`.** — **DONE (commit `7c512c09`).** Instead of casting the `.values(...)` result, both endpoints now construct `ManufacturerSchema` / `PersonSchema` instances directly per the project's "return Schema instances" idiom. No cast, no `dict[str, Any]`.

- **`entity_crud.py` casts `model_cls` to `Any` four times** — **DONE.** `CatalogModel` now inherits `LifecycleStatusModel` (zero-runtime-impact: every concrete subclass already inherited it directly; Python MRO dedupes, Django reports no migration changes). Registrar params narrowed from `type[Model]` to `type[CatalogModel]`; all four `cast(Any, model_cls)` sites and the `cast(Any, obj).status` / `cast(Any, e).slug` / `cast(Any, parent).slug` sites are gone. `LinkableModel` gained instance-level `name: str` / `slug: str` annotations (fields still live on concrete subclasses); the one `_meta.get_field("name")` call in `register_entity_create` needs `# type: ignore[misc]` because django-stubs's plugin can't see a field at the abstract level — the ignore is the only residual cost. The "Idiom for generics over heterogeneous model classes" above was softened — the rationale against a bound TypeVar now rests solely on per-subclass fields (e.g. `RewardType.aliases`), not on the manager.
- **`create_view: Callable[..., Any]`** — **DONE.** Rather than assigning both inner functions to a single widened variable, each branch of `register_entity_create` now calls `router.post(...)(...)` with its own concretely-typed view inline. No shared-variable type widening, no `Callable[..., Any]`.

**Done when:** every bullet above is resolved or explicitly closed with a "won't fix, because..." note in this doc. No baseline-count criterion — these items don't all surface as baseline entries.

All Step 4 items resolved. Baseline: 377 → 375.

## Step 4.7: Idiom-#2 cast sweep — WONT_DO

Originally planned as a sweep to replace `cast(HasModelCount, obj).model_count` with `getattr(obj, "model_count", 0)` across `catalog/api`. On trying the first site ([corporate_entities.py:154](../../../backend/apps/catalog/api/corporate_entities.py#L154)) it became clear the trade is lateral at best:

- **Cast + protocol:** `.model_count` is a real typed attribute access. Typos → mypy error. `HasModelCount` is effectively a structural type for "an object with the queryset-annotated count field" — which is what protocols are _for_.
- **getattr:** `"model_count"` is a magic string. Typos → silently returns `0` forever, no mypy signal.

The idiom-#2 argument ("widens the whole object") is overstated here: the `cast(Has*, obj).field` pattern reads one field and discards the widened reference immediately. There is no cleaner django-stubs-native way to express "this queryset carries these `.annotate()`d attributes" — `.values()` + `TypedDict` would lose model instances and break the prefetch-heavy serializers these endpoints rely on.

**Decision:** keep the `Has*` protocols in [\_typing.py](../../../backend/apps/catalog/api/_typing.py) and the existing `cast(Has*, obj).field` sites. Update idiom #2 when touched to note that queryset-annotated attributes are an exception: prefer a narrow structural protocol over `getattr` for this case.

## Step 5: narrow `apps.*.api.*` decorator relaxation - DONE

Removed the override entirely. Measured fallout in two passes:

1. Scoped the override away from `apps.catalog.api.*` (Step 3.1/3.2 typed every endpoint return, so the Ninja decorators now have enough call-site typing to satisfy `disallow_untyped_decorators`). Zero new baseline entries, zero raw `untyped-decorator` errors in `apps/catalog/api/*`.
2. Dropped the override entirely. Still zero new baseline entries and zero raw `untyped-decorator` errors anywhere — the single-file `apps.{accounts,citation,core,media,provenance}.api` modules are clean too.

The override block at the old `pyproject.toml:136` is gone. If a future Ninja endpoint regresses, the failure will surface as an `untyped-decorator` error against the baseline rather than being silently relaxed.

## Step 6: `core/*` + `conftest.py` - DONE

Typed the shared helpers imported across every app before the per-app steps, so later steps don't stub around untyped imports.

- `apps/core/models.py` — annotated `save`, `unique_slug`, `MarkdownField.deconstruct`, `get_claim_fields`, `RecordReference.__str__`, `_cleanup_references`; parameterized `MarkdownField(models.TextField[str, str])`. `deconstruct` returns `Any` with a one-line comment pointing at Django's `Field.deconstruct` protocol — the 4-tuple is Django's, not ours. `unique_slug` uses `type(obj)._default_manager` instead of `.objects` (per the introspection idiom).
- `apps/core/markdown_links.py` — parameterized the four `dict` generics, dropped the `ValidationErrorMessageArg` TYPE*CHECKING dance (the symbol isn't in `django.core.exceptions` at runtime \_or* in django-stubs; `ValidationError` accepts `list[str]` directly).
- `apps/core/licensing.py` — introduced `_LicenseSeed` TypedDict for the canonical license seed rows (all 22 rows share the same field shape), `SourceFieldLicenseMap = dict[tuple[int, str], License | None]` type alias named once at module top and reused, typed `resolve_effective_license(claim: Claim, ...)`.
- `apps/core/tests/test_markdown_links.py` — `list[dict]` → `list[dict[str, Any]]`.
- `conftest.py` — removed the `persons`/`roles` variable shadowing (the `bulk_create` return was unused; the re-fetch is the one callers consume).

Baseline: 375 → 353.

**Deferred:** `apps/core/markdown.py:95` (`Match` type-arg) and `apps/core/entity_types.py:46` (`type-abstract`) are in the baseline but out of Step 6 scope as stated.

## Step 7: `catalog/api` tail - DONE

The taxonomy-adjacent endpoint files (franchises, themes, gameplay_features, corporate_entities) each had ~7 entries in the same shape as Step 2.2 files. Callees typed first (`catalog/models/*` M2M fields with explicit `ManyToManyField[_To, _Through]` parameters; `catalog/claims.py` `build_relationship_claim` / `build_media_attachment_claim`), then endpoints.

Two new named types landed alongside the type-arg fixes:

- `IdentityPart = str | int | None` on `make_claim_key` in [apps/provenance/models/claim.py](../../../backend/apps/provenance/models/claim.py) — re-exported through `apps.provenance.models`. Replaces inline `str | int | None` at every identity-part call site.
- `RelationshipClaim = tuple[str, JsonBody]` in [apps/catalog/claims.py](../../../backend/apps/catalog/claims.py) — the `(claim_key, value_dict)` pair returned by both relationship-claim builders. `JsonBody` (already in `apps/core/types.py`) is the right alias for the JSON-shaped value dict.

The two `Cannot infer type of lambda` entries on `taxonomy.py`'s `_register_*` wrappers are pre-existing (noted in Step 1) and still deferred.

Baseline: 353 → 310.

## Step 7.1: return-Schema follow-ups surfaced by Step 7 - DONE

Remaining "return Schema, not dict" debt in `catalog/api`. No baseline impact — drift cleanup on files that already satisfy `disallow_untyped_defs`.

- **Restructured the accumulator-then-mutate pattern in `_serialize_system_detail` and `_serialize_person_detail`.** Both helpers built a `dict[str, SomeSchema]` and then mutated the Schema instances in place (`titles[key].thumbnail_url = ...`, `titles[key].roles.append(...)`) as more data arrived in the loop. Replaced with private mutable dataclasses (`_RelatedTitleAccum`, `_PersonTitleAccum`) used during accumulation; the Pydantic Schema is now constructed once per entry at the end of the loop. Schemas are never mutated post-construction.

## Step 8: `citation/api` - DONE

Same pattern as Step 2 — helpers first, endpoints after, `make codegen` between batches. Unlike Step 2, the type catalog was designed up-front (every helper signature, endpoint return type, and schema boundary decided before any code change) to avoid the gradual dict-return reverse-engineering that slowed Steps 1–7.

Scope landed: `citation/api.py` (38 → 0), `citation/url_extraction.py` (7 → 0), plus three adjacent files:

- **`citation/models.py`** — dropped the `has_children: bool` class-level annotation on `CitationSource`. It was a lie: `has_children` only exists on rows from the search queryset's `.annotate(has_children=Exists(...))`. Replaced with a narrow `_HasChildren` Protocol in `api.py` and `cast(_HasChildren, s).has_children` at the one read site (same pattern as the `Has*` protocols in [catalog/api/\_typing.py](../../../backend/apps/catalog/api/_typing.py)).
- **`citation/extractors.py`** — `Recognition`'s four loose `child_id` / `child_name` / `child_skip_locator` fields were tightened into a nested `RecognitionChild | None`. The dataclass now encodes the runtime invariant (child fields are either all present or all absent) in the type, eliminating an `assert rec.child_name is not None` at the consumer and a defensive `rec.child_name or ""` fallback in `url_extraction.py`. Two test mocks flipped from `MagicMock(child_id=…)` to real `Recognition` / `RecognitionChild` instances.
- **`_authed_user(request: HttpRequest) -> User`** — new endpoint-local helper that narrows `request.user` with `assert not isinstance(request.user, AnonymousUser)`. No `cast(User, ...)` needed because django-stubs types `HttpRequest.user` as `User | AnonymousUser` when `AUTH_USER_MODEL` resolves to `auth.User`. Originally added per-app; consolidated to [apps.core.api_helpers.authed_user](../../../backend/apps/core/api_helpers.py) in Step 9.3. When a custom User model lands (see [docs/plans/UserModel.md](UserModel.md)), the helper will need a cast re-added — flagged in the docstring.

Baseline: 310 → 261.

## Step 9: `provenance` - DONE

Scope (19 entries): `provenance/api.py` (15) plus foundational `provenance/models/claim.py` (4). Sequenced callee-before-caller (9.1 → 9.5) with three prep sub-steps to lay a clean substrate.

- **9.1** — renamed `_base.py` → `base.py` across catalog/provenance; converted `apps/media/models.py` to a package.
- **9.2** — relocated `MediaSupported` to `apps/media/models/base.py` and lifted it to `ClaimControlledModel`.
- **9.3** — consolidated `ErrorDetailSchema` and `authed_user` into `apps/core/{schemas,api_helpers}.py`.
- **9.4** — parameterised `ClaimManager(Manager["Claim"])`; typed `assert_claim` and `Claim.for_object` (4 entries).
- **9.5** — typed 5 `provenance/api.py` endpoints; `revert_claim` → `204 None`; flipped media `detach_media` / `set_primary` to `204` (11 entries). `list_review_claims` retained in baseline (4 entries) pending LinkableModel workstream.

Baseline: 222 → 161.

## Step 10: `catalog/resolve/*` - DONE

See [ResolveHardening.md](ResolveHardening.md). Multi-PR sequence that tightens the claim-value contract across the write path, registry, read-path types, and resolver reads. Typing motivation is one of several — the reasoning wins justify the sequence independently — but baseline reduction still counts here: ~44 mypy entries in `catalog/resolve/*` clear across Steps 3–4, plus downstream subscript-flip entries in Step 5.

Scope landed: no `apps/catalog/resolve/*` entries remain in `backend/mypy-baseline.txt`.

## Step 11: `media/*` - DONE

Same pattern as Step 2 — helpers first, endpoints after, `make codegen` between batches. See [MediaTyping.md](MediaTyping.md) for the up-front type catalog and per-step decisions.

Scope landed (~39 entries cleared): `admin.py` (12), `api.py` (9), `apps.py` (8), `processing.py` (6), `tests/*` (4). Two helpers added to `api.py`: `_authed_user` (originally added per-app; consolidated to [apps.core.api_helpers.authed_user](../../../backend/apps/core/api_helpers.py) in Step 9.3 alongside `ErrorDetailSchema`) and a tightened `_resolve_entity` returning `tuple[ContentType, MediaSupported]` via `_default_manager`.

Inline-admin LSP note: django-stubs declares conflicting `obj` types on `BaseModelAdmin.has_*_permission` (child) vs `InlineModelAdmin.has_*_permission` (parent), so `MediaRenditionInline.has_*_permission` uses `obj: Any = None` — flagged in-file as idiom #3.

Baseline: 261 → 222.

## Step 12: Ingestion and management commands - DONE

Grouped because they share patterns (external I/O, command runners, bare dicts from JSON parsing):

- [catalog/management/commands/ingest_pindata.py](../../../backend/apps/catalog/management/commands/ingest_pindata.py) (45 — #1 hotspot)
- [catalog/ingestion/opdb/adapter.py](../../../backend/apps/catalog/ingestion/opdb/adapter.py) (30)
- [catalog/ingestion/ipdb/adapter.py](../../../backend/apps/catalog/ingestion/ipdb/adapter.py) (20)
- [catalog/management/commands/validate_catalog.py](../../../backend/apps/catalog/management/commands/validate_catalog.py) (13)
- [catalog/ingestion/wikidata_sparql.py](../../../backend/apps/catalog/ingestion/wikidata_sparql.py) (12)
- [catalog/ingestion/fandom_wiki.py](../../../backend/apps/catalog/ingestion/fandom_wiki.py) (10)
- [catalog/ingestion/apply.py](../../../backend/apps/catalog/ingestion/apply.py) (4)
- [catalog/ingestion/opdb/records.py](../../../backend/apps/catalog/ingestion/opdb/records.py) (3)
- [catalog/ingestion/bulk_utils.py](../../../backend/apps/catalog/ingestion/bulk_utils.py) (3)
- Adapter tests land with their subjects: [catalog/tests/test_opdb_adapter.py](../../../backend/apps/catalog/tests/test_opdb_adapter.py) (7), [test_ipdb_adapter.py](../../../backend/apps/catalog/tests/test_ipdb_adapter.py) (6).

## Process

- `strict = true` is already global, so the enforcement surface is the baseline itself plus removing relaxations.
- Fail CI on new baseline entries and shrink the file monotonically as each step lands.
