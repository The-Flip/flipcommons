# Citation Plugin System

This document contains the architecture for how the citation subsystem is extended via plugins.

**Status:** everything in this document is built and enforced today, except the [Future directions](#future-directions) section at the end, which is explicitly not built.

## The two plugin frameworks

Two separate plugin frameworks, meeting at exactly one designed seam (the [composition contract](#the-composition-contract)):

- **citation types** (like video) — first-party plugins that are _allowed real programming_: a type module owns code (video's timestamp grammar, its scheme contract class).
- **citation type schemes** (like YouTube) — the third-party unit, locked down to _pure configuration_: a scheme declares facts and carries no code at all.

## The three audiences

Each plugin framework serves three audiences:

- **Plugin author**: writes a plugin for a scheme or type. Sees only what they must fill in.
- **Citation framework**: the machinery that drives every plugin uniformly — the registry, the drivers, the shape compiler, the conformance harnesses.
- **External customer**: code _outside_ the citation framework that uses it without knowing a plugin exists. "External" is relative to the citation framework, not to the backend: `api.py`, the ingest parser and `models.py` are external customers. The `[[cite:` frontend is one tier further out — it calls the Ninja **product API** over HTTP, and that API's handlers are themselves external customers. So the frontend is plugin-blind by construction: it sees JSON (`source_type`, a server-computed access URL), never a spec, scheme, registry or layer.

## The module map

The audiences are **module walls**, not conventions. Inside `apps/citation/citation_types/`:

```text
vocabulary.py                  shared enum + aliases (imports nothing)

CITATION SCHEME FRAMEWORK — pure configuration
citation_scheme_specs.py       scheme-author declarations: the whole authoring surface
citation_scheme_driver.py      framework: the shape compiler + SchemeDriver
schemes/                       one declaration module per platform

CITATION TYPE FRAMEWORK — real programming allowed
citation_type_specs.py         type-author declarations
citation_type_driver.py        framework: CitationTypeDriver runs the declared grammar
book.py magazine.py web.py     the type modules — a type's code lives in its module
video.py

registry.py                    aggregation + the composition weaves (the one seam)
```

- An author module holds declarations an author fills in and nothing else; a framework module holds everything the system _does_ with them.
- A scheme author sees `citation_scheme_specs` plus their owning type's scheme contract class (`video.VideoSchemeSpec`) — never a driver, never the registry, never citation-_type_ authoring.
- A type author writes real code in their type module and declares it to the framework as `LocatorContract` fields; the `CitationTypeSpec` record itself stays fields-only.

## The two extension axes

Two axes, sharply different audiences and change-rates. Everything else follows from taking that difference seriously.

|                | **Citation types**                                                                      | **Schemes**                                                                    |
| -------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Examples       | book, magazine, web, video                                                              | ipdb, opdb, youtube, vimeo, tiktok, x                                          |
| Who writes one | first-party, in-house                                                                   | the third-party drop-in unit                                                   |
| How often      | rare (changes locator semantics + reader UX)                                            | routine (mechanical once the type exists)                                      |
| What it owns   | hierarchy shape, abstractness, the locator contract (grammar, prompt, structured value) | one platform's URL recognition → identifier, canonical URL, optional deep link |
| Contract class | `CitationTypeSpec`                                                                      | `SchemeSpec` (per-type subclass, e.g. `VideoSchemeSpec`)                       |
| May carry code | **yes** — grammar functions in the type module, declared as `LocatorContract` fields    | **no** — pure configuration, proven by a JSON round-trip test                  |
| Belongs to     | —                                                                                       | exactly one type (`source_type`), whose behavior it inherits                   |

A scheme belongs to one type and speaks that type's structured locator value; a type stands alone.

Both axes are model-free and I/O-free — the package is a leaf `models.py` imports one-way; all DB work (child minting, recognition queries, instance writes) stays in core code that consumes the plugins through the framework.

## Scheme framework, surface by surface

**Plugin-author surface.** Everything a scheme author fills in lives in `citation_scheme_specs.py`, and every field is data:

- `url_shapes`: `UrlShape` rows — hosts plus a path pattern with an `{id}` slot, or a query parameter carrying the id. The framework compiles them into one anchored pattern, applying host escaping/anchoring, the id-extension guard and the path terminator itself — an author _cannot write_ a spoofable or truncating pattern; the weird shapes (TikTok's composite id, Vimeo's unlisted-hash tail, X's handle prefix) are expressed inside the shape's path fragment.
- `id_pattern`: the bare-identifier grammar (a regex source string, no capture groups).
- `canonical_url_template` / `deep_link_template`: `str.format` templates over `{identifier}` / `{start_seconds}`. Template substitution suffices by construction — the single-`{id}`-slot shape contract forces the identifier to be one contiguous URL substring (TikTok's composite `user/video/id` identity is designed around it).
- `start_seconds_source`: where a seek hint rides in a URL (query-vs-fragment + param names); the _values_ are parsed framework-side through the owning type's grammar.
- `root_citation_source_info`: the platform root's declared facts, which ingest holds seeding patches to.

**Citation-framework surface.** `citation_scheme_driver.py`: the shape compiler and `SchemeDriver`, which wraps one spec and owns all behavior — compilation at registration (a malformed declaration fails at import), URL recognition (`extract`), identifier validation/normalization and the URL builders. The registry builds one driver per registered spec; behavior is never added to spec classes, and a conformance guard fails the build if it ever is.

**External-customer surface.** Named functions; no customer reaches into spec fields:

- `recognize_scheme(url)` — which scheme + identifier a URL yields, by pattern match alone (plus the start-seconds hint). For `api.py` and the patch parser, which reject a scheme URL cited the wrong way.
- `recognize_url(url)` — the same, resolved against the seeded root; the DB entry point that mints children (`extractors.py`).
- `scheme_source_type(key)`, `normalize_scheme_identifier(key, raw)`, `scheme_root_citation_source_info(key)`, `is_known_scheme(key)`, `known_scheme_keys()` — for the patch parser and `source_upsert.py`.
- `scheme_canonical_url(key, id)`, `scheme_deep_link(key, id, locator)`, `scheme_start_seconds_hint(key, url)` — the canonical-collapse target and the two weave outputs, consumed by `deep_links.py` and `extractors.py`.

The pure queries live in the package root (`registry.py`) — the only part that could ever move to another repo — while the DB operations (`recognize_url`, `deep_linked_url`, child minting) live with the DB code in `extractors.py`/`deep_links.py`. Keeping them apart keeps a real boundary visible: `recognize_scheme` is a pure predicate; `recognize_url` hits the database and creates rows.

**No per-scheme frontend code — deliberate.** Recognition output reaches the client as plain JSON over the product HTTP API (`source_type`, a server-computed deep link), so no per-scheme code exists in the frontend at all. This is what collapses the third-party surface to exactly one Python module — and it is why schemes, unlike types, have no codegen'd frontend channel.

## Type framework, surface by surface

**Plugin-author surface.** A type author writes two things: declarations in the `CitationTypeSpec` record (`source_type`, `flat_hierarchy`, `parentless_abstract`, `child_skips_locator`, `locator`, `scheme_spec_type`) and _real code_ in their type module — the locator grammar functions (video's `parse_start_time`/`format_start_time`), declared to the framework as `LocatorContract` fields, plus the scheme contract class their schemes construct (`VideoSchemeSpec`). The record itself stays fields-only; the code lives in the module and the contract fields.

**Citation-framework surface.** `citation_type_driver.py`: `CitationTypeDriver` runs the declared grammar behind one uniform surface — locator normalization (the write-path validation in `locators.py` runs through it), value parse/format as total, None-guarded methods (the weaves and recognition hint formatting run through it). Plus the registry's coherence checks and constraint-derivation accessors (`identifier_key_choices`, `scheme_bindings`).

**External-customer surface.** Two, genuinely, because type behavior must be mirrored client-side:

- _Frontend (codegen)._ The codegen'd `CITATION_TYPE_META` plus the hand-written `CitationTypeFrontend` interface; the cite UI consults a per-type registry keyed by `source_type` and never sees a spec. Codegen reads `CitationTypeSpec` to _generate_ that channel, which is not a leak.
- _Backend._ `citation_type_spec(source_type)` for behavior facts and `citation_type_driver(source_type)` for behavior — the two chokepoints every customer goes through (`models.py` reads traits via the former; `locators.py` validates via the latter).

## The composition contract

The one seam binding the two frameworks:

> **The type owns the locator value; a scheme speaks only the structured value.**

A video _type_ parses and normalizes `1:02:03` and owns the `StartSeconds` value; a video _scheme_ declares an identifier grammar and URL templates and never sees locator text. The seam is realized as a **pair of weaves in `registry.py`** — the one place scheme data meets type contracts, in both directions:

- **Outbound** — `scheme_deep_link(key, identifier, locator)`: the type driver parses stored locator text into the structured value, the scheme's `deep_link_template` turns the value into a seek URL. `deep_linked_url` (`deep_links.py`) is the model adapter around it.
- **Inbound** — the `start_seconds_source` evaluation inside `recognize_scheme` (exposed as `scheme_start_seconds_hint`): the scheme's source says where a pasted URL carries the hint, the type driver says what the values mean.

Neither layer sees the other's vocabulary, and neither spec class carries any parsing — the weaves live in the framework, not on the plugins. Statically, the seam is `CitationTypeSpec.scheme_spec_type` (a type names the spec class its schemes construct, `isinstance`-checked at registration) and the `identifier_key_scheme_type` CHECK constraint (a scheme root's type is its scheme's owning type).

## Enforcement

The walls are held by the build, not by review:

- **Import-linter, app level** ("Citation app internal stack"): the citation app's exhaustive layer stack, with `citation_types` as a leaf `models.py` imports one-way.
- **Import-linter, package level** ("Citation types plugin-package stack"): the exhaustive nested stack (`registry` → `schemes`/drivers → type modules → `citation_type_specs` → `citation_scheme_specs` → `vocabulary`) — no cycles, every new submodule must be placed.
- **Import-linter, audience walls**: "Citation scheme modules see only declarations" (a scheme module directly importing a driver, the registry or citation-_type_ authoring fails the build) and "Citation type modules see only declarations" (same for type modules and the framework).
- **The no-logic guards**: conformance tests fail the build if a method or property is ever added to a scheme declaration class (`SchemeSpec`, `VideoSchemeSpec`, `UrlShape`, `StartSecondsSource`, `SchemeRootCitationSourceInfo`) or to the `CitationTypeSpec` record. Python cannot statically forbid methods on a dataclass, so the rule is build-failing instead.
- **The JSON round-trip proof**: every registered scheme is serialized to JSON, rebuilt from the parsed document and compared equal. `json.dumps` physically rejects callables, compiled patterns and any live object, so a scheme that smuggles code cannot pass — pure configuration is a _proven_ property, per scheme, forever.

## The framework does the testing

A structured interface is only as strong as its enforcement — so testing is the framework's job, not the author's, on both axes:

- **Scheme conformance** (`tests/schemes/test_conformance.py`), parametrized over the registry: canonical-URL round-trip, junk-identifier rejection, host-anchoring and anti-truncation backstops on the compiler, recognition-host/shape consistency, deep-link well-formedness, hint round-trip through the owning type's grammar, the no-logic guards and the JSON proof.
- **Scheme examples** (`tests/schemes/test_examples.py` + per-scheme tables): each scheme's real URL shapes, exact canonical and deep-link outputs declared as _data_ in a `SchemeExamples` table; the shared harness runs them all. A per-scheme test module is **just the table**.
- **Scheme DB round-trip** (`tests/schemes/test_db_roundtrip.py`): seed the root from its declared facts, mint a child from an alternate URL shape, re-recognize and reuse it, weave — or decline — the deep link. Every scheme gets core-write-path coverage by being registered.
- **Type conformance** (`tests/test_citation_type_conformance.py`), parametrized over the type registry: locator value-grammar round-trips, parse/format pairing, kind-matches-bridge, canonical text survives `normalize`, invalid-message presence, driver totality and the record's no-logic guard. A new type's grammar is verified by the framework the moment it registers.

## Measurable acceptance

Stated so reviews can hold the line:

- **Adding a scheme:** one backend declaration module + one registry line + `makemigrations` + a seeding patch + one test-side example table + its example-registry line. **Zero** frontend code, **zero** core edits, **zero** edits to the owning type's module. More than that means the seam leaked.
- **Adding a type:** one backend module + one frontend module + registry entries + a codegen run.
- A grep for a type or scheme key (`"video"`, `"youtube"`) outside its module, the registry and generated output returns nothing — the framework and its customers name no plugin.
- A grep for `SCHEME_SPECS[` or scheme-spec field reads outside the `citation_types` package, the framework's recognition module (`extractors.py`), the codegen command and tests returns nothing — external customers go through the package-root accessors. `extractors.py` drives every scheme through recognition and minting; it is the exhaustive exemption, and a second module joining it should raise eyebrows.
- The author declaration classes carry no logic, every registered scheme survives the JSON round trip, and no plugin module imports a framework module — all three enforced by the build, not by review.

## Decisions

Recorded so future work inherits them:

1. **The module layout is the audience wall.** Author and framework surfaces are separate modules in each framework, held structurally by the import-linter contracts and build-failing guards listed under [Enforcement](#enforcement) — the boundary is mechanical, never a docstring convention, because conventions erode. The one deliberate exception: the sectioning of `registry.py`'s exports (external-customer vs framework-channel) is convention, because the accessors must live in the module that imports every plugin.
2. **The type backend customer surface is governed by a read-better test, per-trait.** `models.py` reads type traits through the `citation_type_spec(source_type)` chokepoint (`.child_skips_locator`, `.parentless_abstract`, `.flat_hierarchy`). A named accessor on top earns its place only if it reads better at the call site: decided **no accessors** — `self.is_root and …parentless_abstract` keeps the type-level fact visibly distinct from the row-level `is_root` test, where `is_abstract_root(self.source_type)` would look like a row query and blur exactly that split.
3. **Scheme functions split into pure registry queries and DB operations — a real boundary, not a facade to consolidate.** The pure queries live in the `citation_types` package root; the DB operations live with the DB code. Nothing needs them merged, so there is no `scheme_api.py` (every other `*_api.py` in the repo is a Ninja router, so the name would mislead).
4. **Deferred: a generic structured-locator value.** `LocatorContract.parse_value`/`format_value`, the `{start_seconds}` template placeholder and the hint plumbing are hardwired to `StartSeconds = int` in the type-agnostic layer — a future non-`int` locator value (page number, coordinates) means editing shared contracts, not just adding a type module. Deliberately deferred until a second value shape actually exists (audio/podcast will reuse `int` seconds, so it may never bind). Recorded so it is a decision, not an oversight.

## Future directions

### Schemes as stored configuration

A citation type is and will remain first-party code. However, citation schemes will ultimately be authored by third parties in a lightweight fashion NOT subject to us code reviewing it. Citation schemes are ultimately NOT imperative logic, NOT a Python module at all: it should be stored in the databse as configuration, authored in a product UI rather than an IDE, validated by the conformance harness at save time and live without a deploy.

The serialization boundary is the proof mechanism of this: the JSON round-trip test keeps every scheme expressible as such a row today.

The remaining distance:

- **The regex residue.** A shape's path fragment and the id grammar are still regex fragments — fine from first-party authors, but ReDoS vetting (or a further-constrained path syntax) is the gate before any _untrusted_ authoring surface opens.
- **Registration and constraint derivation.** The explicit `_SCHEMES` list and the registry-derived `identifier_key` CHECK constraint assume schemes ship with the code ("greppable beats magic" was decided for in-repo modules). Stored schemes supersede both deliberately: registry-over-rows, and the constraint relaxed to an FK or revalidated on scheme save.
- **The example tables move with the scheme.** Today a scheme's URL examples are test-side data; a stored scheme carries them as part of its own configuration, and the conformance + example harnesses become its save-time validation gate rather than a CI suite.
- **The composition contract is what makes this safe.** A stored scheme can only declare _where_ things live — never how anything is parsed. All parsing stays in first-party type code, woven framework-side in the registry, so a broken or hostile scheme's blast radius is bounded to its own URLs.

**Deliverers move to the database at the same time.** The deliverer table ([CitationSourceMisclassification.md](CitationSourceMisclassification.md)) is the same kind of artifact — per-platform pure configuration authored today as in-repo declarations — and it migrates to UI-authored, DB-stored rows alongside schemes rather than on its own track. It is the easier half: most entries are inert data (hosts, work kind, message noun) with no constraint derivation and no seeded root, so only its regex shapes (ISBN extraction, kind hints) share the regex-residue gate above. Code-shipped entries remain as a floor even then — the misclassification guard must hold on an empty database.

### Citation source misclassification / deliverer hosts

This is the Amazon-book-as-web problem. It's a domain-modeling question, not a plugin-contract one — its plan lives in [CitationSourceMisclassification.md](CitationSourceMisclassification.md), with the rejected-platform reasoning in [VideoCitations.md](VideoCitations.md).
