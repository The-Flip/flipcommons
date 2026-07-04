# Citation Plugin Contract Surfaces

Decision record for how the citation plugin system exposes its contracts. It records _why the investment is asymmetric_ between the two extension axes and defines the surfaces the Stream C refactors (C1–C5) build, so reviews can hold the line against future drift.

Companion to [VideoCitations.md](VideoCitations.md), which owns the plugin architecture and the isolation contract. This sharpens one dimension that doc left implicit: a plugin system has three distinct contract surfaces, and we invest in them **per audience**, not uniformly.

## Open questions

- **Facade home.** A new consumer module inside `citation_types` vs. designating the existing `extractors`/`deep_links`/`locators` functions as the named surface. Leaning: a thin `recognition`/`scheme_api` surface the bypassers import, while the DB-touching helpers (`recognize_url`, `get_or_create_*`) stay where they are and become part of that surface by re-export.
- **Is C4 worth a named surface?** Types are first-party, so the bar is lower — a small accessor (`skips_locator(source)`, `is_abstract_root(source)`) vs. just a documented convention that `models.py` may read `CitationTypeSpec` traits. Resolve when we reach it.

## The model: three surfaces × two frameworks

A plugin system exposes three contracts, to three audiences:

1. **Author-facing** — what a plugin author writes to; their whole view of the system.
2. **Framework-facing** — what the framework calls on every plugin to treat them uniformly; usually private to the framework.
3. **Consumer-facing** — what the rest of the app calls to _use_ the plugin system, without knowing a plugin exists.

The citation system has two extension axes with different audiences:

- **Types** (book, magazine, web, video) — first-party, rare, product-shaped. A new one changes locator semantics and reader UX; always an in-house decision.
- **Schemes** (ipdb, opdb, youtube, vimeo, tiktok, x) — the third-party drop-in unit. Adding a platform is mechanical once its type exists.

## Current state, held to the grid

- **Type consumer surface, frontend: distinct and strong.** The codegen'd `CITATION_TYPE_META` plus the hand-written `CitationTypeFrontend` interface; the cite UI never sees a spec. This is the model of what a consumer surface should be.
- **Schemes have no frontend surface** — deliberate (deep links are computed server-side) and correct.
- **Author (1) and framework (2) conflate for schemes.** `SchemeSpec` carries both the author's input fields (`url_pattern`, `canonical_url`, `root_seed`) and the framework's driver methods (`extract`/`validate_identifier`/`normalize`) on one class. Types don't have this problem: `CitationTypeSpec` is declarative and its behavior lives in `LocatorContract`.
- **Backend consumer surface (3) is unnamed and leaky, for both frameworks.** A facade exists in spirit — `recognize_url`, `deep_linked_url`, `normalized_locator`, `get_or_create_scheme_child`/`get_or_create_external_source` — but consumers bypass it into spec fields: `source_upsert.py` reads `SCHEME_SPECS[…].root_seed`; `api.py` iterates `SCHEME_SPECS` calling `spec.extract(url)`; `claim_ingest/patches/parsing.py` reads `SCHEME_SPECS[…].source_type` and calls `.normalize`/`.extract`. The isolation contract holds for plugin _names_ (no consumer names `youtube`/`video`) but not for _field shape_ — consumers are coupled to the spec's field vocabulary, so changing the spec's shape ripples out.
- **The cross-framework composition contract is unnamed.** "The type owns the locator value; a scheme speaks only the structured value" is what lets `deep_linked_url` weave a type's `parse_value` into a scheme's `deep_link`. It is enforced (registry `isinstance` + the `identifier_key_scheme_type` CHECK + the conformance harness) but expressed nowhere as a designed surface — the most load-bearing contract in the system, and the most implicit.

## Decision: invest asymmetrically by audience

Match the investment to VideoCitations.md's stated priority — schemes isolated more aggressively than types — rather than building three symmetric surfaces on both frameworks.

- **Schemes get the full three surfaces.** They are where strangers write code and where the boundary is weakest.
- **Types get a lighter two.** First-party and rare; the frontend codegen already is their real consumer surface.
- **One explicitly-named cross-framework seam** binds the two.

This is the governing decision. The five refactors below realize it.

## Target surfaces

### Scheme author surface (1)

The `SchemeSpec` fields + the callback Protocols (`CanonicalUrlBuilder`, `DeepLinkBuilder`, …) + `RootSeed` + the per-type `scheme_spec_type` (`VideoSchemeSpec`), plus the authoring helpers `host_prefix` / `ID_BOUNDARY` / `seconds_from_query` / `seconds_from_fragment`. This is everything a scheme author fills in — and nothing they don't.

### Scheme framework / driver surface (2) — **C2**

`extract` / `validate_identifier` / `normalize` — what the framework calls _on_ a spec, built from the author's fields. Name them as the driver surface (a docstring section, or a `SchemeDriver` Protocol the spec satisfies) so an author sees these are invoked on their spec, not authored by them. The conflation with (1) is defensible (a single non-overridable `extract` is why every scheme extracts identically), but it must be _legible_.

### Scheme consumer surface (3) — **C1**, **C3**

A named facade the rest of the app calls, so nothing outside it reaches into `SCHEME_SPECS` fields:

- `recognize_scheme(url)` — which scheme + identifier a URL yields (pure, no DB), for `api.py` and `parsing.py`.
- `scheme_source_type(key)`, `normalize_scheme_identifier(key, raw)`, `scheme_root_seed(key)`, and a known-scheme-keys accessor, for `parsing.py` and `source_upsert.py`.
- The existing DB helpers (`recognize_url`, `deep_linked_url`, `get_or_create_*`) stay where they live and join this surface by designation.

Then split the package `__all__` so **authoring exports** (spec types + Protocols + helpers) and **consumer exports** (the facade + registry accessors) are separate import surfaces (**C3**). Route the three bypassers through the facade (**C1**).

### Type consumer surface, backend, lighter (4) — **C4**

Name the type-trait reads so `models.py` stops reaching into `.child_skips_locator` / `.parentless_abstract` / `.flat_hierarchy` directly — a small accessor surface, or a documented convention (see Open Questions). Codegen legitimately reads `CitationTypeSpec` (it generates the frontend channel) and is not a leak.

### Cross-framework composition contract (5) — **C5**

State "the type owns the locator value; a scheme speaks only the structured value" explicitly in `base.py` and here, with `deep_linked_url` named as its reference implementation.

## Acceptance — how reviews hold the line

- A grep for `SCHEME_SPECS[` or `spec.<field>` outside the scheme facade module returns only the facade itself, the codegen command, and tests.
- The `citation_types` package exposes separate authoring and consumer import surfaces.
- The driver methods (2) and the cross-framework contract (5) are named where an author or reader first meets them.
- Adding a scheme still costs exactly: one module + one registry line + `makemigrations` + a seeding patch + one test-side example table — with zero consumer edits.
