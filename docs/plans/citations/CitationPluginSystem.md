# Citation Plugin System

How the citation subsystem is extended: the two plugin axes (**citation types** and **schemes**), the three contract surfaces each exposes, and the module/layer structure that keeps those surfaces honest and enforceable.

This doc obsoletes the plugin-architecture design in [VideoCitations.md](VideoCitations.md) (its `## The citation-type plugin architecture` section). VideoCitations.md keeps what is genuinely video-specific — the product spec, the stretch-test batch (Vimeo/TikTok/X), the type-homogeneity rule, the movies/audio roadmap, the rejected-platform reasoning and the rollout — and points up here for the general architecture. The work list stays in [PluginArchitectureFollowups.md](PluginArchitectureFollowups.md); this doc is the design those items realize.

The system is real and mostly built. This records the design as it stands and states the contracts precisely enough that a review can hold the line as the system grows.

## The three audiences

A plugin system serves three audiences, and this doc names them the same way throughout:

- **Plugin author** — writes one scheme or type. Sees only what they must fill in.
- **Citation framework** — the machinery that drives every plugin uniformly (the registry, the shared `extract`/`normalize`, the conformance harness).
- **External customer** — code _outside_ the citation framework that uses it without knowing a plugin exists. "External" is relative to the citation framework, not to the backend: `api.py`, the ingest parser and `models.py` are external customers. The `[[cite:` frontend is one tier further out — it calls the Ninja **product API** over HTTP, and that API's handlers are themselves external customers. So the frontend is plugin-blind by construction: it sees JSON (`source_type`, a server-computed access URL), never a spec, scheme, registry or layer.

Each of the two axes exposes a surface to each audience. The rest of the doc walks them.

## Decisions

Resolved in design review; recorded so the C-stream inherits them.

1. **Sub-layer `citation_types` with a dependency-DAG contract — not an audience-enforcement one.** The package's internal imports already form a clean DAG (`registry` → `schemes` → type modules → `url_patterns`/`base`), so an ~8-line nested `layers` contract makes cycles impossible and forces every new submodule to be placed. That is the growth insurance worth buying. It does **not** enforce the plugin-author / framework / external-customer split, because the external-customer accessors live in `registry` (top), which must import every plugin to build `SCHEME_SPECS`. Enforcing that split would need the accessors pulled into their own layer plus a forbidden-contract — real machinery for a marginal gain — so it stays `__all__` + convention, made legible by C3.
2. **The type external-customer surface (C4) is governed by a read-better test, per-trait.** `models.py` already funnels type-trait reads through one accessor, `citation_type_spec(self.source_type).child_skips_locator` (and `.parentless_abstract`, `.flat_hierarchy`). A named accessor on top (`is_abstract_root(source_type)`, …) earns its place **only if it reads better at the call site than the trait read it replaces** — `is_abstract_root` may clear that bar; a pure rename like `nests_flat` may not. Decide per-trait at C4.
3. **Scheme functions split into pure registry queries and DB operations — a real boundary, not a facade to consolidate.** The pure queries live in the `citation_types` leaf; the DB operations live with the DB code. Nothing needs them merged (only `api.py` uses both, importing each by name), so there is no `scheme_api.py`. See [Where the scheme functions live](#where-the-scheme-functions-live).

## The two extension axes

Two axes, sharply different audiences and change-rates. Everything else follows from taking that difference seriously.

|                | **Citation types**                                                                      | **Schemes**                                                                    |
| -------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Examples       | book, magazine, web, video                                                              | ipdb, opdb, youtube, vimeo, tiktok, x                                          |
| Who writes one | first-party, in-house                                                                   | the third-party drop-in unit                                                   |
| How often      | rare (changes locator semantics + reader UX)                                            | routine (mechanical once the type exists)                                      |
| What it owns   | hierarchy shape, abstractness, the locator contract (grammar, prompt, structured value) | one platform's URL recognition → identifier, canonical URL, optional deep link |
| Contract class | `CitationTypeSpec`                                                                      | `SchemeSpec` (per-type subclass, e.g. `VideoSchemeSpec`)                       |
| Belongs to     | —                                                                                       | exactly one type (`source_type`), whose behavior it inherits                   |

A scheme belongs to one type and speaks that type's structured locator value; a type stands alone.

Both axes are **pure**: a spec is declarative facts plus stateless functions — no model imports, no DB, no I/O. They live in `apps/citation/citation_types/`, a dependency-free leaf `models.py` imports one-way. That purity is what makes the specs testable in isolation, movable to another repo, and (eventually) plausible as uploaded plugin code.

**Invest asymmetrically.** Schemes get all three surfaces sharpened — they are where strangers write code and the boundary is weakest. Types get a lighter touch — first-party and rare, and their real customer-facing channel (frontend codegen) is already excellent. The _why_ differs: schemes are isolated for **decoupling** (third-party, growing — the spec's shape must change without rippling); types for **consistency** (first-party, stable — the value is a tidy chokepoint). One named seam binds the axes (the composition contract, below).

## Where the scheme functions live

Two homes, for two needs:

- **Pure registry queries** — `recognize_scheme`, `scheme_source_type`, `normalize_scheme_identifier`, `scheme_root_seed`, `is_known_scheme`, `known_scheme_keys`. Read-only over `SCHEME_SPECS`, no DB. This is the scheme surface an external customer wants in one discoverable place, and the only part that could ever move to another repo (it is `models`-free), so it lives in the `citation_types` package root — in `registry.py`, since they are registry queries.
- **DB operations** — `recognize_url`, `deep_linked_url`, `get_or_create_scheme_child`, `get_or_create_external_source`. They resolve a seeded root or mint rows, so they touch `models` and live with the DB code, in `extractors`/`deep_links`.

Keeping them apart keeps a real boundary visible: `recognize_scheme` is a pure predicate; `recognize_url` hits the database and creates rows. No caller needs the two homes merged — only `api.py` uses both, and it simply imports the two functions it needs. There is no consolidated `scheme_api.py` because nothing asked for one. (The import-linter layer stack, with `citation_types` at the bottom and the DB code in the middle, would forbid a module spanning both anyway — that is confirmation, not the reason.)

One naming point, learned from a false start: the pure surface is the `citation_types` package root, not a new `*_api.py` module. Every other `*_api.py` in the repo is a Ninja router, so `api` on an internal accessor module misleads — and a package-root surface needs no new name.

## Enforcement

The citation app has an **exhaustive** import-linter layer stack (`pyproject.toml`, "Citation app internal stack"), so an unplaced submodule fails the build. Top imports lower; siblings in a `a | b` group may not import each other:

```
api | admin
url_extraction
extractors | extraction | source_upsert | schemas | deep_links | locators
models
psl
hosts | citation_types | safe_fetch | authz | source_node
```

Today it treats `citation_types` as one node. C1 adds a nested `layers` contract so the package's internal DAG (`registry` → `schemes` → type modules → `url_patterns`/`base`) is enforced too — no cycles, every submodule placed (Decision 1). The plugin-author / framework / external-customer split _inside_ the package stays convention (`__all__` + C3), because the external-customer accessors live in `registry`, which must import every plugin.

## Surface-by-surface

### Schemes (aggressively isolated)

**Plugin-author surface (1).** Everything a scheme author fills in, and nothing more:

- The `SchemeSpec` fields: `key`, `label`, `source_type`, `url_pattern`, `id_pattern`, `canonical_url`, `root_seed`, and the optional `deep_link` / `start_seconds_from_url`.
- The callback Protocols they implement: `CanonicalUrlBuilder`, `DeepLinkBuilder`, `StartSecondsExtractor` — named Protocols, not bare `Callable`, so argument meanings show up in the signature. These fields _are_ the third-party API.
- `RootSeed` (platform-root facts) and the per-type spec class they subclass (`VideoSchemeSpec`).
- The authoring helpers that hide the security-sensitive regex plumbing: `host_prefix(*hosts)` (the anchored `https?://<host>` prefix, so a look-alike host can't match), `ID_BOUNDARY` (the shared end-of-identifier lookahead), `seconds_from_query(*params)` / `seconds_from_fragment(*params)` (the near-identical start-seconds extractors). A raw-regex escape hatch stays for genuinely weird shapes (TikTok composite path, Vimeo unlisted hash).

**Citation-framework surface (2) — C2.** `extract` / `validate_identifier` / `normalize` are defined once on `SchemeSpec` and are what the framework calls _on_ the author's fields, so every scheme resolves input identically. Today they sit on the same class as the author fields, conflating (1) and (2). The conflation is defensible — a single non-overridable `extract` is _why_ every scheme extracts the same way — but must be **legible**: an author needs to see these are invoked on their spec, not written by them. C2 names them as the framework surface (a docstring section, or a `SchemeDriver` Protocol the spec satisfies), without splitting the class.

**External-customer surface (3) — C1, C3.** Named functions a customer calls; the isolation rule is that no customer reaches into `SCHEME_SPECS` fields:

- `recognize_scheme(url)` — "which scheme + identifier does this URL yield?", by pattern match alone. For `api.py` and `parsing.py`, which reject a scheme URL cited the wrong way.
- `recognize_url(url)` — the same, but resolved against the seeded root; the entry point that mints children.
- `scheme_source_type(key)`, `normalize_scheme_identifier(key, raw)`, `scheme_root_seed(key)`, `is_known_scheme(key)`, `known_scheme_keys()` — for `parsing.py` and `source_upsert.py`.

C1 routes the three bypassers (`api.py`, `claim_ingest/patches/parsing.py`, `source_upsert.py`) through these functions so nothing outside the leaf reaches into `SCHEME_SPECS` fields. C3 splits the package `__all__` so plugin-author exports (spec types, Protocols, helpers) and external-customer exports (the accessors) are separate import surfaces.

**No per-scheme frontend code — deliberate.** Recognition output reaches the client as plain JSON over the product HTTP API (`source_type`, a server-computed deep link), so no per-scheme code exists in the frontend at all. This is what collapses the third-party surface to exactly one Python module — and it is why schemes, unlike types, have no codegen'd frontend channel.

### Types (lightly isolated)

**Plugin-author surface (1).** The `CitationTypeSpec` fields — `source_type`, `flat_hierarchy`, `parentless_abstract`, `child_skips_locator`, `locator` (a `LocatorContract`), `scheme_spec_type` — declarative behavior facts. A type's behavior is _data_: there are no driver methods on it, because the behavior that would be methods lives on the `LocatorContract` (`normalize`, `parse_value`, `format_value`). So types have no (1)/(2) conflation to resolve.

**Citation-framework surface (2).** The registry's coherence checks and constraint-derivation accessors (`citation_type_spec`, `identifier_key_choices`, `scheme_bindings`) — what the framework runs across all type specs. Already clean.

**External-customer surface (3).** Two of them, genuinely, because type behavior must be mirrored client-side:

- _Frontend (codegen) — the model of a good surface._ The codegen'd `CITATION_TYPE_META` plus the hand-written `CitationTypeFrontend` interface; the cite UI consults a per-type registry keyed by `source_type` and never sees a spec. Codegen reads `CitationTypeSpec` to _generate_ that channel, which is not a leak.
- _Backend — C4, lighter._ `models.py` reads type traits through the `citation_type_spec(source_type)` chokepoint. C4 decides only whether to add trait-named accessors on top (Decision 2).

## The composition contract — C5

The most load-bearing contract in the system, and today the most implicit:

> **The type owns the locator value; a scheme speaks only the structured value.**

A video _type_ parses and normalizes `1:02:03` and owns the `StartSeconds` value; a video _scheme_ is handed `(identifier, start_seconds)` and never sees locator text. This is what lets `deep_linked_url` weave a type's `parse_value` into a scheme's `deep_link` — the type turns stored locator text into `start_seconds`, the scheme turns `start_seconds` into a seek URL. It is what keeps a scheme small: its author writes URL patterns and a parameter syntax, not a timestamp parser.

Enforced today by three mechanisms with no single name: the registry's `isinstance` check, the `identifier_key_scheme_type` CHECK constraint (a scheme root's type is its scheme's owning type), and the conformance harness's round-trip invariant. C5 states the contract explicitly in `base.py` and here, with `deep_linked_url` named as its reference implementation, so the seam is a designed surface rather than an emergent property.

## The framework does the testing

A structured interface is only as strong as its enforcement, and third-party code arrives without house context — so testing is largely the framework's job, not the author's.

- **The conformance harness** is a parametrized suite every registered scheme passes just by being registered: `extract(canonical_url(id))` round-trips; `validate_identifier` rejects junk (empty, overlong, wrong charset, embedded whitespace); URL patterns are host-anchored so a look-alike host can't match; `deep_link` output is a well-formed URL on the scheme's own host for zero and nonzero start times; a `start_seconds` hint round-trips through the owning type's locator grammar.
- **Data-driven examples (E1, built).** Each scheme declares its real URL shapes as _data_ — an example table living test-side in `tests/schemes/`, not on the production spec — and one shared harness runs them across every scheme. A per-scheme test module is that small table plus any genuinely bespoke assertions (X's dual host families, TikTok's composite id), not a hand-rolled parametrize skeleton.

End state: a new scheme is one module (declarative spec + composed helpers) + one registry line + `makemigrations` + a seeding patch + one test-side example table (plus its example-registry line) — the framework does the driving _and_ the testing.

## Measurable acceptance

Stated so reviews can hold the line:

- **Adding a scheme:** one backend module + one registry line + `makemigrations` + a seeding patch + one test-side example table + its example-registry line. **Zero** frontend code, **zero** core edits, **zero** edits to the owning type's module. More than that means the seam leaked.
- **Adding a type:** one backend module + one frontend module + registry entries + a codegen run.
- A grep for a type or scheme key (`"video"`, `"youtube"`) outside its module, the registry and generated output returns nothing — the framework and its customers name no plugin.
- A grep for `SCHEME_SPECS[` or `spec.<field>` outside the `citation_types` leaf, the framework's two DB-operation modules (`extractors.py`, `deep_links.py`), the codegen command and tests returns nothing — external customers go through the package-root accessors. The two DB-op modules are the citation framework itself (audience 2) driving the specs, not customers; they are the exhaustive exemption list, and a third module joining it should raise eyebrows.
- The `citation_types` package exposes separate plugin-author and external-customer import surfaces.
- The framework surface (2) and the composition contract (5) are named where an author or reader first meets them.

## Realization: the C-stream

The refactors that bring the code up to this design. Tracked in [PluginArchitectureFollowups.md](PluginArchitectureFollowups.md); listed against the surfaces they build.

- **C1 — scheme accessors in the leaf + nested layer contract.** Add the pure registry queries to the `citation_types` package root (`registry.py`); route the three bypassers through them; add the ~8-line nested `layers` contract (Decision 1). No new app module.
- **C2 — name the scheme framework surface.** Make `extract`/`validate_identifier`/`normalize` legible as framework-invoked, not author-written.
- **C3 — split the scheme package `__all__` by audience.** Plugin-author exports vs external-customer exports.
- **C4 — type backend external-customer surface.** Apply the read-better test per-trait (Decision 2).
- **C5 — name the composition contract** in `base.py`, with `deep_linked_url` as reference impl.

Tracked separately, not part of the C-stream: source misclassification / deliverer hosts (the Amazon-book-as-web problem) is a domain-modeling boundary, not a plugin-contract question — see Stream F in the follow-ups doc and the rejected-platform reasoning in [VideoCitations.md](VideoCitations.md).
