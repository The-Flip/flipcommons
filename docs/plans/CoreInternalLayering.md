# Core Internal Layering — break the markdown/validators cycle so `core` can be a layered contract

`core` is the one app whose internal boundary is enforced via import-linter by an enumerated `forbidden` contract rather than a clean `layers` contract, because its top-level import graph has a cycle. This plan identifies the down-up edges that cause it and the relocations that remove them, so `core` can get the same exhaustive layered contract `catalog` now has.

## Open questions

- **Where does `bulk_create_validated` land** once it leaves `core/validators.py` — a `core/models/` operations module (it needs `TimeStampedModel`, so at/above models), or a higher layer? Its current home is the `validators → models` edge.
- **How do we relocate `MarkdownField` without re-introducing `models → markdown`/`wikilinks` at runtime?** The field's authoring↔storage conversion is wikilink-aware, and grimp counts function-local imports, so the conversion must stay above the models layer — see [The fix](#the-fix).
- **Is the payoff worth doing now, or opportunistically?** The current enumerated forbidden is green and adequate; the upside (a complete, self-policing layered contract) is real but not urgent.

## Context

The import-linter rework gave `catalog` an exhaustive `Catalog internal layers` contract (`containers` + `exhaustive`), but left `core` as the enumerated `The core api layer is a leaf` `forbidden` contract. The reason is structural: a `layers` contract requires a DAG, and `core`'s top-level graph is not acyclic. The enumerated forbidden is strictly weaker — it is hand-maintained and already incomplete: its source list omits `admin`, `checks`, `soft_delete` and `apps`, so those modules are unpoliced against importing `core.api`. An `exhaustive` layered contract would close that gap automatically. See [AppBoundaries.md](../AppBoundaries.md).

## The finding: two down-up edges, not one

`core` has exactly one cycle — a single strongly-connected component `{autocomplete, markdown, models, validators, wikilinks}`. It is tempting to call `models → markdown` the lone keystone — deleting just that edge from the _current_ graph does leave it acyclic — but that test is misleading, because the fix doesn't delete an edge, it **relocates a module, which carries its own imports along**. Two down-up edges actually have to be inverted:

1. `models → markdown` — `core/models/mixins.py:15` imports `MarkdownField` from `core.markdown`.
2. `validators → models` — `core/validators.py:58`, a function-local `from apps.core.models import TimeStampedModel` inside `bulk_create_validated` (already commented "avoid circular import").

They interact, which is the trap: relocating `MarkdownField` into `core/models/fields.py` removes edge 1 but **adds** `models → validators`, because `MarkdownField` carries `validate_no_mojibake` as a default validator (`field.py:20,43`). With `validators → models` still present, that is a new `models ↔ validators` 2-cycle. Verified with grimp: relocating `MarkdownField` alone leaves `[[models, validators]]`; relocating it _and_ severing `validators → models` is fully acyclic.

## Root cause: two mis-homed pieces

Both edges are a lower layer reaching up, for the same reason — model-layer code living in a higher module:

- `MarkdownField` is a Django field type (model-layer infrastructure) living in the `markdown` rendering package, so `core/models/mixins.py` must import _up_ to declare fields with it.
- `bulk_create_validated` is a generic model operation — it takes a `Model`, validates, then bulk-creates — living in `core/validators.py`, so `validators` must import `core.models`. It is the _only_ models-importer in that module; the rest of `validators` (e.g. `validate_no_mojibake`) is pure and model-free.

## The fix

Two relocations, each moving a model-layer concern down/out so every remaining edge points up:

1. **Move `MarkdownField` → `core/models/fields.py`** (where `_contribute_max_length_check` already lives), leaving the rendering / wikilink-conversion / reference logic in `core/markdown`. The subtlety: `MarkdownField`'s authoring↔storage conversion is wikilink-aware (the conversion helpers in `field.py` lazy-import `core.wikilinks`), and grimp counts function-local imports — so if the relocated field calls those conversions at runtime it re-creates `models → markdown`/`wikilinks` and the cycle returns. Split field-_storage_ (the class itself — `__init__`, `deconstruct`, `formfield`, `contribute_to_class`, max-length check, the pure mojibake validator) from wikilink-aware _conversion_ (stays in `core/markdown`, invoked from above the models layer — the save/serialization path or a registered hook, never from inside the field).
2. **Move `bulk_create_validated` out of `core/validators.py`** — it's a model operation, not a validator. Relocate it into `core/models` (an operations-style module) or a higher layer, so `core/validators.py` keeps only pure, model-free validators (`validate_no_mojibake`, …) that `models.fields` can import without a cycle.

After both, `core` is acyclic (verified): `validators` and `models` become bottom-layer, with `markdown → wikilinks → autocomplete` and the rest sitting cleanly above.

## Payoff

Once `core` is acyclic, replace `The core api layer is a leaf` with an exhaustive `Core internal layers` `containers` contract, mirroring `catalog`: a self-documenting tier stack (roughly `api`/`apps`/`admin` on top, down through `markdown → wikilinks → autocomplete`, the leaf utilities, to `models`/`validators`/`types`/`schemas`/`search` at the bottom — derive the exact tiers from the graph once the cycle is gone), with `exhaustive = true` so a new core submodule that isn't placed fails the build. That closes the `admin`/`checks`/`soft_delete`/`apps` gaps the enumerated contract silently leaves today.

## Scope and sequencing

- **Independent** of the model-driven work and of [ModelDrivenClaimResolution.md](model_driven_metadata/ModelDrivenClaimResolution.md). This is pure core-internal health, not a step toward domain-swappability.
- **Opportunistic / low priority.** The enumerated forbidden is green and adequate; do this when `core` is being touched anyway, or when the layered-contract completeness is wanted for its own sake.
- **Verification gate:** the new exhaustive `Core internal layers` contract goes green with **zero baselines** — the same bar held in the import-linter rework. A required baseline means a down-up edge remains (the `MarkdownField` runtime-conversion tie, or an un-severed `validators → models`) and the cycle isn't fully broken.
