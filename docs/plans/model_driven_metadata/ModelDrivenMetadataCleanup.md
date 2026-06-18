# Model-Driven Metadata Cleanup

Companion doc to the umbrella [ModelDrivenMetadata.md](ModelDrivenMetadata.md). The umbrella establishes the [principles](ModelDrivenMetadata.md#principle-the-model-is-the-source-of-truth), [design patterns](ModelDrivenMetadata.md#design-patterns), [antipatterns](ModelDrivenMetadata.md#antipatterns), [smell catalog](ModelDrivenMetadata.md#smells), and [rules of thumb](ModelDrivenMetadata.md#rules-of-thumb).

This doc is the roadmap for bringing the codebase into line with [ModelDrivenMetadata.md](ModelDrivenMetadata.md).

## Roadmap

Each item has its own per-feature doc with the full design, examples, and step-by-step plan; this table sequences them.

| #   | Item                                    | Type              | Doc                                                                      | Blast radius       | Depends on |
| --- | --------------------------------------- | ----------------- | ------------------------------------------------------------------------ | ------------------ | ---------- |
| 1   | Soft-delete attrs hoist                 | Hoist             | [ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md)     | Small              | —          |
| 2   | `immutable_after_create` (new)          | New behavior      | [ModelDrivenImmutableAfterCreate.md](ModelDrivenImmutableAfterCreate.md) | Small-medium       | —          |
| 3   | Linkability (LinkableModel + factories) | Steel thread      | [ModelDrivenLinkability.md](ModelDrivenLinkability.md)                   | Large (in flight)  | #2         |
| 4   | Location CRUD validation                | Steel thread      | [LocationCrud.md](LocationCrud.md)                                       | Large              | #3         |
| 5   | API endpoint ownership                  | Reconcile plan    | [ModelDrivenEntityContract.md](ModelDrivenEntityContract.md)             | Large              | #3, #4     |
| 6   | `WikilinkableModel` mixin               | New mixin + hoist | [ModelDrivenWikilinkableMetadata.md](ModelDrivenWikilinkableMetadata.md) | Medium             | (after #3) |
| 7   | `NamedModel` base                       | New base          | [ModelDrivenNamedMetadata.md](ModelDrivenNamedMetadata.md)               | Large (~14 models) | —          |
| 8   | Resolver signature standardization      | Cleanup           | (inline below)                                                           | Small              | —          |

**Status** (the table's "in flight" annotations above predate these landings): **#1** (soft-delete hoist), **#3** (Linkability — main body; only its follow-ups remain), and **#6** (`WikilinkableModel`) are ✅ **done**. **#4** (Location CRUD) has its backend committed; the frontend write routes remain. Still to do: **#2** (`immutable_after_create`), **#5** (API endpoint ownership — see [ModelDrivenEntityContract.md](ModelDrivenEntityContract.md) vs [ModelDrivenApi.md](ModelDrivenApi.md), unreconciled), **#7** (`NamedModel`), and **#8** (resolver signature standardization, independent — can land any time).

**Suggested order for the remainder:** **2**, then **4**'s frontend, then **5**, then **7**.

### Resolver signature standardization

Mechanical prep work without its own per-feature doc:

1. Rename `entity_ids` → `subject_ids` on bespoke resolvers (`resolve_all_corporate_entity_locations`, `resolve_media_attachments`, and any others surfaced by the audit). Rename existing `model_ids` callers too.
2. Drop the unused `dict[str, int]` stats return from `resolve_all_corporate_entity_locations` (no consumer reads it).
3. Confirm every bespoke resolver conforms to `(subject_ids: set[int] | None = None) -> None` after the above.

Originally scoped as prep for `CatalogRelationshipSpec`; lands cleanly as an independent refactor regardless of whether that spec ever revives.

## Deferred

Items where the right moment hasn't arrived. Each links to its own status doc.

- **`CatalogRelationshipSpec`** — the typed-spec axis for catalog through-model relationships. Deferred pending a second independent consumer; status in [ModelDrivenCatalogRelationshipMetadata.md](ModelDrivenCatalogRelationshipMetadata.md).
- **`CitationSourceSpec`** — the typed-spec axis for citation source families. Deferred pending a third structured-parser source family; status in [ModelDrivenCitationSourceMetadata.md](ModelDrivenCitationSourceMetadata.md).
- **`_SOURCE_FIELDS` in `citation/seeding.py`** — hand-sync'd frozenset of scalar columns on `CitationSource`. Folds into the `CitationSourceSpec` work when that revives; landing it standalone now would mean touching citation seeding twice.
- **`MEDIA_CATEGORIES` readiness validator** — `ready()`-time check that every concrete `MediaSupported` subclass declares a non-empty `MEDIA_CATEGORIES`. Optional; not blocking anything.
- **`entity_types.py` cosmetic alignment** — swap module-level `_ENTITY_TYPE_MAP: dict | None = None` + `global` for `@functools.lru_cache(maxsize=1)` on a build function, matching the canonical typed-spec template. Purely cosmetic.

## Done

Shipped work, kept as a record so the lessons stay attached to the worked examples that produced them.

- **Shape 2 typing sweep.** Typed `claim_fk_lookups`, `claims_exempt`, `soft_delete_cascade_relations`, `soft_delete_usage_blockers` as proper `ClassVar`s. The `soft_delete_*` attrs went through a tuple-then-frozenset correction that surfaced the "semantics over RHS shape" principle.
- **`claims_exempt` hoist.** Moved the default onto `ClaimControlledModel`, relocated `get_claim_fields()` to `apps.provenance.models.introspection`, narrowed it to `type[ClaimControlledModel]`, and replaced the consumer-side `getattr` fallback with direct attribute access.
- **`claim_fk_lookups` hoist.** Moved the default onto `ClaimControlledModel`, narrowed FK claim resolution/validation to `type[ClaimControlledModel]`, and replaced resolver/validator `getattr` fallbacks with direct attribute access.
- **`entity_type` / `entity_type_plural` typing.** Promoted to `ClassVar[str]` on `LinkableModel`. `Literal[...]` was considered and rejected — see the "`Literal[...]` over abstract bases recreates drift" principle.
- **`AliasBase` explicit identity attr.** Replaced the `_meta.verbose_name`-derived claim namespace with an explicit `alias_claim_field: ClassVar[str]` declared per subclass, enforced by `__init_subclass__`, parity-tested. Surfaced the "enforce at startup" and "parity tests pin derived sets" principles.
- **Cache-invalidation signal list.** Replaced the hand-maintained 8-model list with an app-registry walk at `ready()` time, widening to 22 models and fixing latent staleness for taxonomy edits made outside the claims pipeline. Surfaced the "blanket inclusion beats opt-in markers" principle.
