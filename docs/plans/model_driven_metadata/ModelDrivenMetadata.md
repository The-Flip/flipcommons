# Model-Driven Metadata

## Goal: make the system as model-agnostic as possible

The project has accumulated model-specific knowledge in subsystems that have no business knowing which catalog model they're dealing with. It shows up across every layer: the claims and provenance core, the URL/href layer, the API surface, the media pipeline, validation, and substantial portions of the frontend.

The signature is uniform: explicit `if isinstance(entity, X)` / `entity_type == "y"` branches; hardcoded field names that happen to be right for most models but not all (`slug`, `name`); parallel hand-maintained registries that enumerate the same model set Django already knows about; and pairs of files that are 95% identical with the model import at the top doing the only real work.

Every new catalog model pays this tax. Adding one means touching the provenance core, adding a write router, wiring an edit-history loader, wiring a sources loader, adding a delete-flow submitter, editing several enumerating registries, building a frontend section registry, building an editor switch, and laying out a route tree — most of which is mechanical reproduction of the previous model's setup.

The cost compounds, and the code that should be most stable — the provenance core, the link layer, the media pipeline — keeps growing branches where it shouldn't. We need those systems to be hardened and easy to reason about.

## Principle: the model is the source of truth

The goal is to encode as much of the knowledge that varies as possible **into the Django models themselves**. The models are the source of truth. Derive metadata from Django introspection whenever possible; declare only the minimum that Django can't express.

## Desired end state

- **The provenance and claims core is fully model-agnostic.** The resolver, the FK lookup machinery, the materialization path, `execute_claims`, the page-level edit-history and sources endpoints, the validation pipeline — none of them contain per-model branches. They read declarations off the model and act accordingly.
- **The URL/href and routing layer is fully model-agnostic.** Link construction reads the model's declared URL pattern; route lookups go through `entity_type` + `public_id`; nothing hardcodes `slug` as the URL key.
- **The API delivery layer is model-driven without making models HTTP-aware.** Entities declare framework-neutral content shape and write surfaces; shared API infrastructure owns route registration, schemas, request/response wiring, and OpenAPI output for list, detail-page, claim patch, create, lifecycle, edit-history, and sources endpoints.
- **Most of the frontend is model-agnostic.** Shared CRUD components, editor base components, edit-history page, sources page, delete flow, and create flow operate against generic API contracts keyed on `entity_type` and `public_id`. Per-model files exist only where there are **legitimate UI differences** — a hierarchy needs a parent picker, curated divisions need a divisions editor, a thumbnail needs an uploader. Everything else collapses into the shared layer.
- **Adding a new catalog model is a declaration, not a code expansion.** A new model declares its ClassVars, participates in the entity-type registry, declares its framework-neutral entity contract, and provides a frontend section registry plus any genuinely model-specific editor components. The provenance plumbing, URL layer, list/detail endpoints, edit-history / sources / delete endpoints, and the bulk of the frontend route tree all light up automatically.

## Smells

### Code-shape smells

- a specific catalog model name (`Theme`, `Location`, `Manufacturer`, `CorporateEntity`, etc.) appears in shared infrastructure (`apps/provenance/`, `apps/core/`, shared frontend components) outside docstring or example contexts. `grep -rn "Theme\|Location" backend/apps/provenance/ backend/apps/core/` returning hits is the diagnostic. Common flavors:
  - **Branching on type.** `isinstance(entity, X)` / `entity_type == "y"` to choose behavior. Hidden form: a `dict` keyed on model class or entity-type string used as a dispatch table.
  - **Model-named functions in shared code.** `build_theme_url`, `resolve_location_path`, `serialize_manufacturer_for_history`. The shared function should take `model` or `entity_type` as a parameter; the model-named version is the smell.
  - **Direct model imports.** `from apps.catalog.models import Theme` inside a shared module that's supposed to work for every catalog model.
- a hand-maintained list, set, dict, or constant enumerates the same model set Django already knows about. Examples: signal lists that subscribe handlers to "every catalog model", cache-invalidation registries, frontend route-dir skip lists, `_SOURCE_FIELDS`-style per-model field maps. The fix is `__subclasses__()` walk + (at most) a marker base class.
- per-model API files in `apps/catalog/api/` own route decorators for standard entity endpoints. If two files differ mostly in model import, queryset, serializer, and response shape, route ownership belongs to shared API infrastructure; the per-entity code should be framework-neutral behavior hooks only.
- per-model frontend route trees contain page logic instead of thin wrappers around shared components — a `+page.svelte` that does anything more than pass `path` / `entity_type` to a shared component is suspicious.
- a hardcoded field name (e.g. `slug`) in shared code where the right answer is a declared ClassVar (e.g. `public_id_field`). The signature is "this works for every model except the one that breaks the convention."

### Test-shape smells

- the parameterized test suite that walks the entity-type registry has a per-model skip list (e.g. `UNMAPPED_ROUTE_DIRS` in `catalog-meta.test.ts`). Every entry in such a list is an admission of an unfixed gap.
- per-model test files duplicate the same provenance/URL/CRUD assertions across models with only the model import changed. The generic suite should cover those; per-model tests should only cover genuine UI/semantic differences.

### Process and tooling smells

- adding a new catalog model produces a PR that diffs `apps/provenance/`, `apps/core/`, or shared frontend components. The diff to those layers should be zero; if it isn't, a generic seam is missing.
- a bug fix has to be applied N times — once per model — instead of once in shared infrastructure. "I fixed this for Theme, now let me apply the same fix to Location and Manufacturer" is the diagnostic.
- a missing or malformed model declaration only surfaces at first request, not at startup. `manage.py check` should catch it; if it doesn't, the system check for that axis is missing.
- [ModelDrivenMetadataViolations.md](ModelDrivenMetadataViolations.md) is non-empty. Its size is a direct measurement of distance from the goal.

## Design patterns

The toolkit for moving knowledge onto models. The patterns are in order of increasing commitment. **Pick the smallest one that fits**; don't reach for a typed spec when a `_meta` walk will do.

### Pattern: `_meta` walk

**When to use it.** The answer is a filter or transform of information Django already carries. Common idioms:

- **Field shape** (name, type, nullability, unique, default) → `_meta.get_field(name)`.
- **FK target + lookup** → `field.related_model` + convention ("pk" unless overridden).
- **M2M through-models** → `Model.m2m_attr.through` or explicit `through="..."` declarations.
- **Reverse relations** → `_meta.get_fields()` / attribute access.

Canonical example in the codebase: [`get_claim_fields(model)`](../../backend/apps/provenance/models/introspection.py) — walks `_meta.get_fields()`, filters by field type and per-model `claims_exempt`, returns a dict. No registry, no caching (cheap enough to recompute). Hand-maintained lists like `_SOURCE_FIELDS` are the natural targets for this pattern.

A `_meta` walk can also read ClassVars inherited from a [base class / mixin](#pattern-base-class--mixin) as per-model inputs — `claims_exempt` declared on `ClaimControlledModel` is the canonical case, used as a filter input by `get_claim_fields` above.

### Pattern: base class / mixin

**When to use it.** The default home for any ClassVar that customizes per-model behavior. The base declares the ClassVar with a default and (optionally) shared methods; subclasses inherit and override the ClassVar where needed. Discovery is `__subclasses__()` of the base — no hand-maintained list of who participates.

This pattern covers the full range, from "marker base with one ClassVar and zero methods" to "behavior-providing mixin." The minimum is just: a typed default declared on a base, so the model class itself is the contract, not a `getattr` call in the consumer. (The opposite shape — bare ClassVar on a subclass, read via `getattr` — is the [field-on-model antipattern](#antipattern-field-on-model).)

Examples in the codebase:

- **`LinkableModel`**: provides `get_absolute_url()`, the `public_id` property, and a default `link_url_pattern` derivation; subclasses declare `entity_type`, `entity_type_plural`, `public_id_field`.
- **`ClaimControlledModel`**: provides claim-related machinery shared across catalog models; the home for the landed `claims_exempt` and `claim_fk_lookups` ClassVars (with defaults of `frozenset()` and `{}` respectively), and the planned home for `immutable_after_create`.
- **`AliasModel`**: provides alias-table conventions; subclasses declare the FK to their owning entity.
- **`MediaSupported`**: marker base whose only job is to host `MEDIA_CATEGORIES` declarations and let the media pipeline enumerate participants.

Use [base class / mixin](#pattern-base-class--mixin) whenever the [`_meta` walk](#pattern-_meta-walk) isn't enough. Use [typed spec](#pattern-typed-spec) instead when the metadata is structured data consumed by multiple independent subsystems and you need startup-time validation. The two compose: `LinkableModel` uses [base class / mixin](#pattern-base-class--mixin), and [`core/entity_types.py`](../../backend/apps/core/entity_types.py) is a [typed spec](#pattern-typed-spec) registry built by walking `LinkableModel.__subclasses__()`.

Rules:

- Keep the base narrow: one capability per base. `LinkableModel` doesn't try to also be the claim-control base; that's a separate mixin.
- Avoid grab-bag bases that bundle several unrelated capabilities. If a model would inherit only to get one of three orthogonal capabilities, split the base.

The cross-cutting rules in [Rules of thumb](#rules-of-thumb) — _Base annotates, subclasses assign_; _Hoist to the smallest base that captures the audience_; _Enforce at startup, not at first request_ — also apply to this pattern.

### Pattern: typed spec

**When to use it.** A concern earns a typed spec when it's consumed by multiple subsystems, when its absence should fail at startup rather than at first request, or when it has a stable shape worth declaring once and validating centrally. Each orthogonal concern gets its own typed, narrowly-scoped class attr.

**Shape.** Typed `ClassVar[Spec]` on the model + introspection registry over an abstract base. Proposed for `CatalogRelationshipSpec`.

#### Why one typed spec object and not N separate class attrs

- Single import to grep for.
- Single schema to evolve.
- One `ready()`-time validator asserts every member of the target set has a well-formed spec.
- Retrofitting a consolidation later would mean touching every affected model twice.

#### Canonical template

Rank-ordering the existing "correct examples" surfaced inconsistencies; this is the composite best-of:

| Concern               | Do this                                                                                                                                                                                                                                                                                                                                                                           | Why                                                                                                                                                                                                       |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Identity              | Declared class attr, typed `ClassVar[Spec]`                                                                                                                                                                                                                                                                                                                                       | Convention-based identity (e.g. deriving a namespace from `_meta.verbose_name`) is fragile; explicit declaration doesn't drift.                                                                           |
| Discovery             | App-registry walk: `apps.get_app_config("...").get_models()` (or `apps.get_models()` for cross-app) + `issubclass(Base)`, skipping `_meta.abstract == True`. Use `apps/catalog/_walks.py:catalog_app_subclasses(base)` for catalog-scoped walks. Recursive `__subclasses__()` is reserved for non-Django Python class hierarchies (e.g. `CitationSource` polymorphic registries). | Matches [`core/entity_types.py`](../../backend/apps/core/entity_types.py). No hand-maintained list, and the app registry handles abstract intermediates that bare `__subclasses__()` would silently drop. |
| Cache                 | `functools.lru_cache(maxsize=1)` on the build function                                                                                                                                                                                                                                                                                                                            | Cleaner than a module-level `None`-init global; no `global` keyword, no nullable type.                                                                                                                    |
| Readiness guard       | Explicit `apps.check_apps_ready()` at the top of the build function                                                                                                                                                                                                                                                                                                               | Relying on a docstring ("must be called after app registry is ready") is how bugs ship.                                                                                                                   |
| Build-time validation | Raise `ImproperlyConfigured` on: missing spec, duplicate identity, referenced fields not resolvable via `_meta`                                                                                                                                                                                                                                                                   | Fails at startup instead of at first request.                                                                                                                                                             |
| Return type           | Typed `NamedTuple` or `@dataclass(frozen=True)` of derived schemas                                                                                                                                                                                                                                                                                                                | Avoids callers indexing into raw dicts.                                                                                                                                                                   |
| Public API            | Single lookup function, e.g. `get_relationship_schema(namespace, content_type=None)`                                                                                                                                                                                                                                                                                              | Internals stay module-private; consumers don't know about the walk.                                                                                                                                       |

#### Best current examples

There is no single perfect file to copy. The current best examples are best for different parts of the pattern:

- **Best `_meta` walk:** [`get_claim_fields()`](../../backend/apps/provenance/models/introspection.py) — derives claim-controlled fields from Django field metadata, with `ClaimControlledModel.claims_exempt` as the only per-model input.
- **Best base-ClassVar contract:** [`ClaimControlledModel`](../../backend/apps/provenance/models/base.py) — declares typed defaults for `claims_exempt` and `claim_fk_lookups`; consumers read direct attributes from `type[ClaimControlledModel]`, not `getattr(..., default)`.
- **Best subclass registry skeleton:** [`core/entity_types.py`](../../backend/apps/core/entity_types.py) — class attr + app-registry walk + app-readiness guard + duplicate validation + narrow public lookup API. Still uses a nullable module cache; use `lru_cache(maxsize=1)` for new code.
- **Best discovery-helper cache:** [`_alias_registry.py`](../../backend/apps/catalog/_alias_registry.py) — `catalog_app_subclasses(AliasModel)` walk, `lru_cache(maxsize=1)`, typed `NamedTuple` return, and explicit `alias_claim_field` identity enforced by `AliasModel.__init_subclass__`.
- **Best runtime schema validator:** [`provenance/validation.py`](../../backend/apps/provenance/validation.py)'s `RelationshipSchema` / `ValueKeySpec` registry — typed frozen schemas, registration-time invariant checks, duplicate-schema rejection, and a small public API. Caveat: it is intentionally hand-registered today, not model-owned metadata; use it for validation shape, not discovery shape.

**Don't copy:** `MEDIA_CATEGORIES` + `MediaSupported` (no discovery helper, no validator); `export_catalog_meta` for runtime metadata (it is a codegen/distribution pattern, not a Python runtime registry).

#### Worked example

One typed spec is designed but deferred:

- `CatalogRelationshipSpec` → [ModelDrivenCatalogRelationshipMetadata.md](ModelDrivenCatalogRelationshipMetadata.md) (claim-relationship metadata).

A second candidate, `CitationSourceSpec`, was also evaluated and deferred — see [ModelDrivenCitationSourceMetadata.md](ModelDrivenCitationSourceMetadata.md).

#### When to add a new typed spec axis

Two failure modes to guard against: within-spec drift (a single spec grows grab-bag fields) and across-spec drift (a model accumulates so many specs that the _set of declarations_ is itself the drift surface).

**Within-spec drift.** If you want to add a field to an existing spec, ask whether the consumer is the same subsystem the spec was built for. If not, it's a new axis and deserves its own attr. If a field could plausibly live in two specs, put it in the narrower one and let the broader consumer read through.

**Across-spec drift — when a new axis is justified.** "One axis, one spec" prevents grab-bag specs but says nothing about axis count. A model carrying six orthogonal specs still accumulates six things-to-remember-when-adding-a-model; the failure mode just moved. A new typed spec axis must pass all four tests:

1. **≥2 genuinely independent consumers.** "Validator + dispatcher in the same resolution pipeline" does not count — same subsystem, same read path, same cadence of change. "Backend claim resolver + frontend edit metadata" does — different subsystems, different release cycles.
2. **Orthogonal to existing axes.** No field overlap; different question answered. If a proposed field could plausibly live on an existing axis, it belongs there — or the slicing between axes is wrong and needs rethinking before adding another.
3. **Stable shape.** The field set converges as consumers grow, not diverges. If each new consumer adds a field, it's a grab bag in slow motion.
4. **Alternative explicitly considered.** Confirm [`_meta` walk](#pattern-_meta-walk) and [base class / mixin](#pattern-base-class--mixin) genuinely can't do it. [Base class / mixin](#pattern-base-class--mixin) handles more than you'd guess.

Meta-norm: no model carries a spec it doesn't apply to. Absence is default; declaration is opt-in per axis.

**Profile objects.** A related temptation: when frontend editing or page behavior gets complicated, it can look attractive to define a per-entity **profile object** that bundles API names, edit affordances, relationship sections, etc. into one UI-facing structure. That is fine _only_ if the profile is a derived view composed from the underlying specs + `_meta`, and stays a narrow UI/API concern. It must not become a second hand-maintained catalog registry. Defer introducing any such layer until the duplication it would eliminate is real, not speculative.

### Pattern: codegen

**When to use it.** Model metadata needs to reach consumers that can't import Python — the SvelteKit frontend, the OpenAPI schema, external tools, any sibling service. The patterns above cover Python runtime consumers; codegen extends any of them to non-Python consumers.

The canonical example already in the codebase: `export_catalog_meta` generates `frontend/src/lib/models/model-meta.ts` from Django models. The rules generalize to any upstream shape → any downstream artifact:

- Generators read models + specs + `_meta`. They never invert the dependency.
- Generated artifacts are derived and not hand-edited; checking them into git is fine but they stay clearly downstream.
- Each generator carries a parity test that fails when the upstream shape drifts from the emitted artifact.

Reuse this pattern when a new spec has to reach another language or runtime. Do not build a parallel hand-maintained schema on the consumer side.

## Antipatterns

### Antipattern: field-on-model

Declaring a ClassVar on a single model subclass and reading it from a generic consumer via `getattr(model, "thing", default)`.

Why it's an antipattern: the contract lives in the consumer's `getattr` — which picks the attribute name, default, and type — not on any class. The system can't:

- enumerate which models opted in (no base to walk via `__subclasses__()`),
- type-check the declarations (no shared type to conform to),
- catch typos at startup (a misspelled or absent attribute silently returns the default),
- evolve the contract without visiting every consumer (rename = grep risk).

The fix is the same in every case: hoist the ClassVar onto the relevant base or mixin with a typed default, so the model class itself is the contract. See [base class / mixin](#pattern-base-class--mixin).

Concrete examples in the current codebase:

- **Wikilink-picker `link_*` attrs** (`link_sort_order`, `link_label`, `link_description`, `link_autocomplete_*`): declared bare on the four ordered linkable types (Title, MachineModel, Manufacturer, Person); read via `getattr(model, "link_*", default)` six times in [catalog/apps.py](../../backend/apps/catalog/apps.py)'s wikilink registration loop. Belong on a new `WikilinkableModel` mixin — see [ModelDrivenWikilinkableMetadata.md](ModelDrivenWikilinkableMetadata.md).

Fixed examples that now show the right shape:

- `claims_exempt` and `claim_fk_lookups` are declared on `ClaimControlledModel` in [provenance/models/base.py](../../backend/apps/provenance/models/base.py), and consumers read them directly from `type[ClaimControlledModel]`.
- `alias_claim_field` is declared on `AliasModel` in [catalog/models/base.py](../../backend/apps/catalog/models/base.py) as `ClassVar[str]`, with `__init_subclass__` enforcement in the same file. Consumers in [\_alias_registry.py](../../backend/apps/catalog/_alias_registry.py) read `alias_cls.alias_claim_field` directly — no `getattr` fallback needed because the contract is enforced at the base.

## Rules of thumb

Cross-cutting rules that apply to any work in this space — picking ClassVar shapes, designing registries, choosing where to enforce, writing parity tests. Some are restated in pattern-specific `Rules:` lists above; this section is where the cross-pattern rules live.

- **Semantics over RHS shape.** Pick the collection type that matches the meaning of the attr, not what the literal happens to look like. `soft_delete_*` started as `tuple[str, ...]` because the RHS was a tuple literal; the right type was `frozenset[str]` because order and duplicates are meaningless. Update the literal at the same time as the annotation.
- **Don't lie about the shape in the annotation.** Consumer-side `getattr(..., default)` defaults must match the annotated type. If the annotation says `frozenset[str]`, the default is `frozenset()`, not `()`. Don't smuggle a mismatched default past the type checker.
- **Base annotates, subclasses assign.** Annotate the `ClassVar` on the base; concrete subclasses assign values without re-annotating. Canonical examples: `MEDIA_CATEGORIES` on `MediaSupported`, `entity_type` on `LinkableModel`, `alias_claim_field` on `AliasModel`.
- **Hoist to the smallest base that captures the audience.** A `ClassVar` meaningful for every claim-controlled model belongs on `ClaimControlledModel`, not above or below. Each per-feature doc's "Why this lives on X" section repeats the audience argument.
- **Blanket inclusion beats opt-in markers** for correctness-critical paths. An opt-in flag like `bust_all_cache_on_save: ClassVar[bool]` would recreate the drift surface a `__subclasses__()` walk is meant to eliminate. Default-on is fail-safe-by-construction.
- **Parity tests pin derived sets.** When a registry, signal list, or set is derived from a `_meta` walk or `__subclasses__()` walk, the parity test asserts the _expected output_, not `derived == derived`. New models fire the test and get reviewed intentionally.
- **Enforce at startup, not at first request.** `__init_subclass__` validators or `apps.checks` system checks catch missing or malformed declarations at boot. The check lives where the contract lives.
- **Document coverage gaps in code, not just PR discussion.** A comment in `signals.py` explains why `MachineModel*` through-rows aren't in the cache-invalidation walk (the claims resolver invalidates directly via `transaction.on_commit`). PR discussion is searchable; code comments are findable.
- **`Literal[...]` over abstract bases recreates drift.** Considered for `entity_type` and rejected: a base `Literal` union spanning all subclasses must stay in sync with the subclass declarations — exactly the drift surface the model-driven approach eliminates. `__init_subclass__` validation + the registry builder catch typos at import time, which is effectively as early as type-check time for this codebase.

## Alternatives considered and rejected

### Rejected alternative: catalog metadata DSL

An alternative would be to define catalog entities, claim-controlled fields, relationship shapes, resolver behavior, API metadata, and frontend-facing metadata in a separate domain-specific schema, then generate Django models and derived code from that schema.

Appeal: one intentionally-designed source of truth could describe the whole catalog surface, including things Django cannot express. In theory, adding a new model or relationship would mean editing one schema entry and regenerating the rest.

Rejected because:

- It would create a second modeling layer above Django. We would still need to understand and debug the generated Django models, migrations, ContentTypes, admin behavior, ORM relations, and type-checking output.
- The project already has working Django model introspection patterns. Replacing those with generation would throw away useful native framework semantics instead of leaning on them.
- Code generation has its own drift surface: generator logic, generated files, migration output, handwritten escape hatches, and review diffs all become part of the maintenance burden.
- The hard cases here are not field declarations. They are semantic ownership questions: claim identity, subject side, shared namespaces, payload-only keys, resolver dispatch, and polymorphic attachments. A DSL would still need declarations for those; it would only move them farther from the models they describe.
- Retrofitting a generator into an active Django app is a large architectural commitment. The current pain can be addressed incrementally by moving small declarations onto model classes and deriving runtime schemas from `_meta`.

The model-owned metadata approach gets most of the centralization benefit while preserving Django as the actual persistence and relationship authority.
