# Model-Driven Citation Source Metadata

## Status: deferred

The `citation_source_spec` axis is not built. The existing extractor registry (`apps/citation/extractors.py`) already absorbs part of this surface; the full typed spec is deferred until a third extractor-backed source family is imminent (only `ipdb` and `opdb` exist today).

Sibling doc to [ModelDrivenMetadata.md](ModelDrivenMetadata.md). The umbrella doc establishes the principle ("Django model is source of truth; one axis, one typed spec"). This doc is the design for the `citation_source_spec` axis — the typed spec that unifies the citation-source identity metadata currently scattered across extractor code, Django model fields, CHECK constraints, and seed data.

## Scope

`citation_source_spec` describes a citation source family — IPDB, OPDB, Fandom, etc. Consumed by:

- URL recognition (extractors)
- Ingest adapters (1:1 with source families)
- The `Citation` model + `identifier_key_valid` CHECK constraint
- Seed data
- Source-priority ranking (claim conflict resolution)
- Display / branding in the UI

The "citation" qualifier is deliberate: "source" is overloaded in this codebase — ingest sources, claim sources, data sources. `CitationSourceSpec` names the specific concept without collision.

This doc does **not** redesign the extractor, the `Citation` model, or ingest adapters — those are downstream consumers. It also does not design `catalog_relationship_spec`; that's a separate axis with its own sibling doc ([ModelDrivenCatalogRelationshipMetadata.md](ModelDrivenCatalogRelationshipMetadata.md)).

## What shape is this, really?

This axis is not structurally parallel to `CatalogRelationshipSpec`, even though the umbrella doc names them side by side. The difference matters enough to state up front.

`CatalogRelationshipSpec` is **per-model metadata**: `MachineModelGameplayFeature` is a model, the spec is a class attr on that model, one-to-one. The model is the source of truth; the spec describes its role.

Citation source families (IPDB, OPDB, Fandom) are **not models**. They are rows in `CitationSource`. And one of the required pieces of per-family information — the URL recogniser — is a regex plus a Python callable. That single fact forces the design:

- The spec cannot live on `CitationSource` rows (can't store a callable as data).
- The spec cannot live only in migrations (runtime consumers need the regex + builder).
- The spec must be **code** colocated with a per-family code artifact.

The natural code artifact is a class-per-family: an abstract `CitationSource` base with `IPDBSource`, `OPDBSource`, `FandomSource` subclasses, each declaring its own `identifier_key`, regex, builder, and display metadata. The Django `CitationSource` table becomes a projection of the registered set, populated at `ready()` time.

That pattern is best described as a **polymorphic behavior registry with a sidecar data table**, not "model-owned metadata." It reuses the Shape 3 machinery from [`core/entity_types.py`](../../backend/apps/core/entity_types.py) (abstract base + `__subclasses__()` walk + `lru_cache` + `check_apps_ready()` + typed lookup), but it is not an instance of the umbrella's "Django model is the source of truth" principle. Readers expecting symmetry with `CatalogRelationshipSpec` should recalibrate here.

Consequence for the options discussion below: Options 1 and 2 are not real alternatives. Option 1 (on the adapter) conflates citation-source identity with ingest-adapter logic — they're 1:1 today but don't have to be, and layering prevents the `Citation` model from importing adapters. Option 2 (on `CitationSource` rows) is impossible because of the callable. Option 3 (class-per-family registry) is the only viable shape. The remaining design question is what the class hierarchy looks like, not where it lives.

## What this replaces

One Cluster 2 violation from [ModelDrivenMetadataViolations.md](ModelDrivenMetadataViolations.md), plus partial overlap with Cluster 4. An honest accounting of the drift surface, because the rhetorical "four touch points" count doesn't survive scrutiny:

- **`EXTRACTORS` dict in `citation/extractors.py`** — genuine parallel registry, replaced by subclass declarations. One surface.
- **`IdentifierKey` `TextChoices` + `identifier_key_valid` CHECK constraint** — logically one surface, not two. Both are migration-state artifacts regenerated from the same registered set via `makemigrations`; a migration author doesn't hand-edit them independently.
- **Website seed data** — not really a drift surface that "goes away." Adding a new source family always means putting a row in `CitationSource`. Whether that row is declared in a seed-data module or inside an `ensure_row()` call on the subclass is a cosmetic shift. The count of declaration sites stays at 1.

Net: ~3 declaration surfaces collapse to ~1.5 (subclass declaration + a `makemigrations` run whenever the registered set changes). The improvement is real but narrower than a naïve "four places become one" reading suggests. The CHECK constraint in particular is baked into SQL, not read from code at runtime — this axis cannot make it fully runtime-derived.

- **Cluster 4 (row 10) — adapter `resolve_hooks`.** Not a pure Cluster 2 violation — each adapter picks a subset of resolvers based on what it actually writes — but the _available set_ of resolvers per source is metadata this spec can own. Revisit once `CitationSourceSpec` and `CatalogRelationshipSpec` both exist.

## Field audit: does the spec earn its keep?

The umbrella doc's rule for whether a field belongs on a shared spec: **≥2 consumers**. Fields with only one consumer belong on that consumer, not on the spec. Applied honestly to the candidate fields:

| Field                                                            | Extractor | CHECK | Seed | Priority | UI  | Adapter | Consumers |
| ---------------------------------------------------------------- | :-------: | :---: | :--: | :------: | :-: | :-----: | :-------: |
| `identifier_key`                                                 |     ✓     |   ✓   |  ✓   |    —     |  —  |    ✓    |   **4**   |
| `display_name`                                                   |     —     |   —   |  ✓   |    —     |  ✓  |    —    |   **2**   |
| URL-recogniser bundle (`url_pattern`, `id_pattern`, `build_url`) |     ✓     |   —   |  —   |    —     |  —  |    —    |     1     |
| `description`                                                    |     —     |   —   |  ✓   |    —     |  —  |    —    |     1     |
| `homepage_url`                                                   |     —     |   —   |  ✓   |    —     | (?) |    —    |     1     |
| `priority`                                                       |     —     |   —   |  —   |    ✓     |  —  |    —    |     1     |
| Brand visuals (icon, color)                                      |     —     |   —   |  —   |    —     |  ✓  |    —    |     1     |

Two important qualifications:

- The URL-recogniser bundle has one consumer on paper, but it is the **reason the spec must be code at all**. Without it, a data-only registry would suffice. It belongs on the spec by construction, not by the ≥2 rule.
- Most `CitationSource` rows have no `identifier_key` (Pinside, PinWiki, Kineticist, Pinball News — verified in `seed_data/websites.py`). This axis is not about all citation sources; it's specifically about the **subset with a structured URL parser**, which today is exactly IPDB and OPDB. Scoping accordingly:

### What the minimum viable spec looks like

Under the ≥2 rule plus the URL-recogniser exception, the spec shrinks to:

- `identifier_key` — class attr.
- `display_name` — class attr.
- `recognize_url()` / `build_url()` / `id_pattern` — class methods / attrs (the reason the spec is a class).

Everything else (`description`, `homepage_url`, `priority`, brand visuals) stays with its single consumer: seed data, ranking config, UI code. They do not move onto the spec just because the spec exists.

### Consequence for the "do this now" call

The field audit makes the cost/benefit concrete:

- Today: 2 source families with structured parsers (IPDB, OPDB). Drift surface per the honest accounting above is ~3 declaration sites → ~1.5.
- The spec, even under its maximum defensible shape, only consolidates `identifier_key` + the URL-recogniser. `display_name` is a minor add.
- The existing backend extractor registry already absorbed part of this surface.

Two honest options:

1. **Defer.** Document the trigger ("revisit when a 3rd structured-parser source family is imminent") and move on. The catalog axis has unambiguous ROI; this one does not at current scale.
2. **Minimal-now.** Build the class-per-family registry with just the three essentials above. Skip priority, branding, adapter-ownership, CHECK-autogeneration tooling until a second consumer concretely needs each. This is a much smaller piece of work than the rest of this doc implies and does not need `CatalogRelationshipSpec` to land first.

Minimal-now makes sense only if a 3rd extractor-backed source is known to be coming. Otherwise defer.

## Open design questions

The "where does the spec live" question is settled above by the callable constraint: a class-per-family registry is the only viable shape. The real open questions are narrower:

- **What goes on the base class vs. a spec dataclass?** Some fields are naturally method-valued (`recognize_url`, `build_url`); others are data (`identifier_key`, `display_name`, `homepage_url`). Unclear whether to mix them on the subclass or split declarative data into a `ClassVar[CitationSourceSpec]` the way `CatalogRelationshipSpec` does. Deferred until the field list is pinned down.
- **Which fields actually earn a place on the spec?** Before this axis is worth implementing, each proposed field should be checked against the "≥2 consumers" rule from the umbrella doc. A thin spec ( `identifier_key` + display name) that hands off everything else to adapter/UI code may not justify the machinery.
- **Does this get done now, or after the Nth extractor?** Today there are two extractors (IPDB, OPDB); Fandom goes through domain-match rather than an extractor. The existing backend extractor registry already consolidates part of this surface. A reasonable answer is to defer until a third extractor-backed source family is imminent and revisit then.

## Prerequisites

None, structurally. The Shape 3 template to copy is [`core/entity_types.py`](../../backend/apps/core/entity_types.py) (the umbrella's "gold" example), not `CatalogRelationshipSpec`-in-progress — they are superficially similar but discover different kinds of things (existing Django model subclasses vs. a newly-invented class hierarchy). This axis has no dependency on the catalog axis landing first; if anything, its smaller blast radius makes it a plausible pilot for the Shape 3 machinery.
