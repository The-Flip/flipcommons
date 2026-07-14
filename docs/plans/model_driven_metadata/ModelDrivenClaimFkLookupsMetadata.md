# Claim FK Lookups

## Status: RETIRED

`claim_fk_lookups` no longer exists. FK claim values now store the target row's integer PK (not a public_id string), so no per-model lookup-key override is needed anywhere in the claims layer: resolution looks up by `pk`, validation existence-checks by `pk`, and the only public_id→row translation left is at authoring boundaries (patch YAML, API payloads), which use `public_id_field` via `resolve_fk_target_pk` in `apps/provenance/claims.py`. The sections below describe the retired design for historical context.

## Historical status: DONE

Landed in PR #281 (`refactor/model-driven-claims-metadata`).

## Context

This work is part of the family described in [ModelDrivenClaimsMetadata.md](ModelDrivenClaimsMetadata.md), and an instance of the broader pattern in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): encode per-model behavior on the model itself, consume it generically from shared infrastructure.

`claim_fk_lookups` is the per-model knob that maps FK fields to the lookup field on the related model. By default the claims layer assumes every FK claim value is the related row's `slug`. When that assumption is wrong — typically because the related model's URL identifier isn't `slug` — the writing model declares an override.

The need is exposed by [ModelDrivenLinkability.md](ModelDrivenLinkability.md): as soon as a related model's `public_id_field` isn't `slug`, the FK claim value must follow.

## The contract

`ClaimControlledModel` declares:

```python
claim_fk_lookups: ClassVar[dict[str, str]] = {}
```

Default empty — every FK claim resolves through `slug` (the historical assumption). Location declares:

```python
claim_fk_lookups: ClassVar[dict[str, str]] = {"parent": "location_path"}
```

When writing the `parent` FK claim, the resolver reads `getattr(parent, "location_path")` rather than `parent.slug`. The same map drives FK resolution at materialization time: `_resolve_fk_generic` in `apps/catalog/resolve/_helpers.py` looks up the related row by its `location_path` instead of its `slug`.

The same map also drives FK claim validation: `validate_fk_claims_batch()` groups pending FK claims and checks target existence with `model_class.claim_fk_lookups.get(field_name, "slug")`, so write-time validation and materialization agree on the lookup key.

## Landed state

This hoist landed in PR #281. `claim_fk_lookups` is now the contract on `ClaimControlledModel`, not an ad-hoc subclass attr discovered by consumer-side `getattr`.

What changed:

- `ClaimControlledModel` declares `claim_fk_lookups: ClassVar[dict[str, str]] = {}`.
- Subclass declarations remain as overrides of the base default.
- FK resolution, FK validation, catalog validation, and shared write factories read `model_class.claim_fk_lookups` directly.
- The claims chain signatures were narrowed to `type[ClaimControlledModel]` where these reads happen, so the direct attribute access is type-visible.
- Runtime behavior is unchanged: the default lookup remains `slug`, and Location's `parent` FK uses `location_path`.

## Why this lives on `ClaimControlledModel`

FK claim lookups are meaningful only for models that participate in claim control — claim writes resolve FKs by some lookup key, and claim materialization reverses that. `ClaimControlledModel` is the smallest base that captures the audience. Hoisting puts the contract on the class the consumer already knows about, lets the type checker enforce the shape, and lines up with the rest of the [claims metadata family](ModelDrivenClaimsMetadata.md) — same base, same hoist recipe.
