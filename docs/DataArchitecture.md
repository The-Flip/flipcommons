# Data Architecture

This documents the architecture of how data flows through the system.

## The Layers

Catalog data moves through different layers depending on whether you are a 🧑‍🦰 human (a contributor using the UI) or a 🤖 data source (the curated data patches). The architectural difference between humans and data sources is bulkification: humans generate one single ChangeSet at a time -- they click Save when editing a record, that creates a ChangeSet -- whereas data patches can ingest 100,000 ChangeSets at once in bulk.

```text
🧑‍🦰 Humans                  🤖 Data Patches
______________________________________________
⬇️ Sveltekit UI            ⬇️ Data Patch System
⬇️ Catalog API             ⬇️ Ingest System
___________ provenance system ________________
             ⬇️ Claims System
             ⬇️ Resolution System
_____________ database ___________________
             ✅ Postgres or SQLite
```

## Foundational Provenance Layer

The provenance foundation is shared by every write path:

- The **Claims System** stores durable attributed facts: who asserted a value, for which entity and field or relationship member, with what evidence and audit grouping.
- The **Resolution System** derives the current catalog view from those facts: it chooses the winning claims and materializes model fields, relationship tables and lifecycle state.

See [Provenance.md](Provenance.md) for the claims and resolution model. See [Citations.md](Citations.md) for how evidence attaches to claims, and [RecordLifecycle.md](RecordLifecycle.md) for create/delete/restore semantics built on top of claims.

## Data Patch System

The data patch system owns the YAML-based [data patch authoring language](DataPatches.md). It parses and validates numbered YAML patch files. It is the source-driven write front end; the only other way data gets into the system is interactive human writes.

The data patch system does not write database rows directly; it outputs an `IngestPlan`, the contract consumed by the ingest system. Patch-specific concepts belong here: YAML syntax, file-order behavior, same-patch references, patch-only diagnostics and same-patch reference resolution.

In compiler terms the patch system is a **front end**: it parses the YAML patch language, resolves and validates each entry, and _lowers_ it to an `IngestPlan` — the **intermediate representation** — which the ingest **back end** (`apply_plan`) executes. The front end and back end stay decoupled across the `IngestPlan` boundary, and the patch system never writes rows itself. Treat that split as load-bearing: new patch behavior belongs in the front end against the IR, not as a fork of `apply_plan`.

The patch front end keeps a **symbol table** (`PatchEntityRegistry`) binding each reference (`entity_type.public_id`) to the entity it names — a committed entity, or an entity an earlier entry in the same patch creates. It resolves _references to entities_, not _claims to values_: it makes same-patch backward references work, and stops there. It is not a second resolver and not a second claims system.

## Ingest System

The ingest system owns execution of an `IngestPlan`. The data patch system is currently its only front end, but it stays source-agnostic by design: by the time `apply_plan()` runs, the front end has already lowered its input into planned entity creates, claim assertions, claim retractions and hooks.

The ingest system creates planned entities, resolves temporary handles, builds unsaved claims, validates claim payloads, diffs against existing active claims from the same source, persists claims and audit rows, attaches citations and invokes resolution for the affected entities.

The ingest system does not own claim semantics. It executes the plan and calls the claims and resolution systems at the right points.

## Interactive Write Path

Human contributors get data into the system through the SvelteKit UI and catalog API write endpoints. Those endpoints validate request payloads, build `ClaimSpec` values and call `execute_claims()` or `execute_multi_entity_claims()`.

Interactive writes do not go through `IngestPlan`. They already represent one user action at a time, so they write claims directly inside a user `ChangeSet`, attach any citation and call `resolve_after_mutation()` for the touched entity and fields.

The same claims model applies to every user action. A create writes ordinary field claims inside a `ChangeSet` with action `create`; an edit writes replacement claims with action `edit`; a delete writes `status = deleted` claims with action `delete`; undo writes compensating claims with action `revert`.

## Claims System

The claims system owns durable provenance facts from both write paths. A claim records that a source or user asserted a value for one field or relationship member on one entity. Sources and users provide priority and enablement inputs; ChangeSets group claim changes into audit events; citation instances attach evidence to claims; retractions and superseding manage active versus inactive claim state.

The claim stream is the system of record for user-inputted catalog fields. Catalog entity rows are the resolved projection, not the durable truth.

## Resolution System

The resolution system owns the current catalog view derived from claims. It is invoked by both write paths: interactive writes call `resolve_after_mutation()`, while ingest calls batch entity resolution and any plan resolve hooks. In both cases, resolution reads active, eligible claims, ranks them by source/user priority and recency, then materializes the winners onto Django model fields, relationship tables and lifecycle state.

Resolution is where scalar values, FKs, relationship membership and `status` become the current catalog rows that pages and APIs read. The resolution system must be deterministic: the same claim set should always produce the same materialized catalog view.

Each resolved dimension has its own **merge policy**, in the CRDT register/set vocabulary — naming them keeps the special cases visible:

- **scalar / FK / `status`** are **last-writer-wins registers**: the single highest-priority eligible claim wins, recency (then `pk`) breaking ties.
- **relationship membership** is a **set** resolved with **per-element last-writer-wins**, _not_ add-wins — each member is independently winner-picked and an `exists=false` tombstone can win and remove it. (Unioning members instead of ranking them is a recurring bug; the set is not add-wins.)

The materialized catalog rows are a view over the claim log. The governing rule for anything that needs a resolved value is to **reuse and compose the resolver's primitives** — the winner-pick (`ranked_claims`), the exists-filter (`member_is_present`), the liveness rule (`is_live`) — and never reimplement the semantics in a second place. A second implementation is exactly where a derived value drifts from what `apply_plan` will actually produce; the primitives are consolidated to single definitions so they can be reused, not re-spelled.

## Write Paths

The interactive human path is:

```text
human contributor
  -> SvelteKit UI
  -> catalog API write endpoint
  -> execute_claims()
  -> persist user ChangeSet and claims
  -> resolve_after_mutation()
  -> materialized catalog state
```

The source-driven data-patch path is:

```text
patch YAML
  -> patch compiler
  -> IngestPlan
  -> apply_plan()
  -> persist claims and audit rows
  -> resolve affected entities
  -> materialized catalog state
```

The important boundary for source-driven data is the `IngestPlan`. Patch code stops there. The ingest backend starts there. Interactive UI writes intentionally bypass that boundary because they already operate on one user action at a time and can write the user `ChangeSet` directly.

## Boundary Rules

- Patch-specific concepts belong in the data patch system: YAML syntax, file-order behavior, same-patch references, patch-only diagnostics and same-patch reference resolution.
- Source-agnostic execution belongs in the ingest system: plan validation, entity creation, claim construction, claim diffing, persistence and run reporting.
- Interactive request handling belongs in catalog API endpoints and edit helpers: request validation, `ClaimSpec` planning, user `ChangeSet` creation and citation attachment.
- Durable attribution belongs in the claims system: claims, sources, users, ChangeSets, citation instances, active/inactive claim state and source priority.
- Current-value semantics belong in the resolution system: winner ranking, scalar and FK materialization, relationship membership materialization and lifecycle visibility.
- A higher layer may call a lower layer, but it should not reimplement the lower layer's semantics. In particular, anything that ranks claims or resolves a value uses the resolution system's own primitives (`ranked_claims`, `member_is_present`, `is_live`), never a re-spelled copy — that is the rule that keeps a derived value from drifting from what the real apply path produces.
