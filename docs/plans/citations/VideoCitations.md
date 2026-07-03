# Video Citations

Product spec and design for a **video citation type** — citing a moment in a video as evidence — and the **citation-type plugin architecture** it forces. The two travel together: video is the first citation type whose locator has real semantics (a timestamp that validates, normalizes and deep-links), so it is the forcing function for isolating per-type knowledge behind one crisp API instead of scattering a fourth type across the codebase.

## Context

### The problem with the current YouTube support

Citing a video is unlike citing a web page: the URL identifies the _work_, but the evidence lives at a _moment_ in it — "start watching at 1:02:03". The locator is the point of the citation.

Current YouTube support conflates two axes that video pulls apart:

- **Identifier scheme** (`identifier_key="youtube"` plus the `Extractor` in `extractors.py`): collapses every YouTube URL shape (`watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`, `/live/`) to one canonical child source per video id. This is dedup and it is genuinely good — it stays.
- **Source type**: YouTube children are minted as `source_type="web"` (hardcoded in `get_or_create_scheme_child`), and the web trait row says `child_skips_locator=True` — "the URL _is_ the locator". For a video that is exactly backwards: today a YouTube cite gets **no locator prompt at all**, so the one thing a video citation needs is the one thing the flow refuses to collect.

So the unwind is not deleting the YouTube scheme; it is recasting what its children _are_.

### The unwind window

Prod has ingested through patch **0038** and no YouTube citations shipped in ≤0038, so nothing YouTube-shaped is live. Patches ≥0039 (in [flippatch](https://github.com/deanmoses/flippatch)) are ours to rewrite, and local dev DBs reset to the `backend/db.pre-0039.sqlite3` snapshot and re-ingest (`ingest_patches --patches-dir`). That means the model change needs **no data migration** — only schema — and the YouTube root's own seeding patch is rewritable in place.

### The architecture goal

Citation type implementations should be **isolated from the core system behind a crisp API**, so new ones can be authored easily and in isolation — eventually movable to a separate repo, or (much later) uploadable plugin code from privileged users. That end-state is not this plan's deliverable, but this plan builds the seam: after it lands, nothing outside the registries knows a "video" or a "youtube" exists, which is the precondition for extraction later.

There are **two extension axes with different audiences**, and the design treats them differently:

- **Citation types** (book, magazine, web, video) — first-party, rare, product-shaped: a new one changes locator semantics and reader UX, so it will always be an in-house decision.
- **Platform schemes** (youtube, and later vimeo, twitch, archive.org) — the expected **third-party unit**. Adding a platform is mechanical once its type exists: URL shapes, an id grammar, a canonical URL, a deep-link parameter syntax. This is the surface strangers will write, so it gets the most isolation and the most structured interface — a scheme author should be handed a small typed contract, not a codebase tour.

## Product spec

### What a video citation is

A video citation cites a **video child** source under a **platform root** (the YouTube root), with an optional **start-time locator** — where to begin watching to find the evidence. Hierarchy is flat (platform → video, no channel level), matching web. Locators are a point in time, not a range: no end times, matching the point-citations philosophy in [CitationDecisions.md](CitationDecisions.md) — a range looks more precise than contributors will reliably maintain.

The locator is **optional**: citing a whole video (a documentary that is itself the evidence) is legitimate, so the locator stage keeps its Skip affordance.

### Timestamp grammar

Accepted input forms, all normalized on write:

- bare seconds: `95` → `1:35`
- colon forms: `1:35`, `1:02:03` (and sloppy variants like `1:2:3` → `1:02:03`)
- unit form: `1h2m3s`, `95s`, `2m` → `1:02:03`, `1:35`, `2:00`

Canonical stored form is **human-readable**: leading unit unpadded, inner units two-digit, hours segment only when ≥ 1 hour — `0:57`, `1:35`, `12:05`, `1:02:03`. Human-readable wins over raw seconds because `locator` is displayed verbatim in every current reader surface (references section, tooltip, Sources page) and in patch YAML under review.

The **backend grammar is authoritative**: normalization and validation run on every write path — API instance mint, the save payload's `citations` list, and patch apply. A malformed locator on a video cite fails loudly (a 422 from the API, a hard patch error at apply) rather than storing junk. The frontend mirrors the grammar for inline UX only.

### Authoring UX

- **Paste**: pasting any YouTube URL shape recognizes the video (existing extractor behavior), creates or reuses the video child one-click, and then — the change — proceeds to the **locator stage instead of skipping it**, with a type-supplied prompt (placeholder `e.g. 1:02:03`) and inline validation. Input stays a plain text field; no multi-part duration widget.
- **Paste prefill**: a pasted URL carrying a start time (`?t=95`, `&t=1h2m3s`, `?start=95`) extracts the video id **and** seeds the locator field with the normalized timestamp. This is the concrete forcing function for the extractor interface change below: `extract` returns `(identifier, locator_hint)`, not a bare id.
- **Search**: selecting an existing video child from source search lands on the same timestamp-prompting locator stage.

### Reader experience

A video citation renders like any other reference entry — source name, `(1:02:03)` locator text — but when a locator is present the entry's link becomes the **deep link** (`https://www.youtube.com/watch?v=<id>&t=3723s`), so "inspect the evidence yourself" is one click to the right moment, not a link plus manual scrubbing. The visible locator text stays alongside the deep link; the transformation applies wherever citation links render (references section, citation tooltip, entity Sources page).

### Data patches

- `sources:` grows `video` as a legal `source_type` (the YouTube root's own declaration becomes `source_type: video`).
- `cite: youtube:<id>` syntax is **unchanged**, as is the `locator:` key on the `cite:` mapping — but a `locator:` on a video cite is now validated against the timestamp grammar at apply time and stored normalized.

## Data model

The schema change is small by design; the core stays type-agnostic.

- **`SourceType.VIDEO`** joins book/magazine/web. Trait row: `flat_hierarchy=True` (platform → video, grandchildren rejected), `parentless_abstract=True` (the YouTube root is a container, never cited directly — recognition always resolves to a video child), `child_skips_locator=False` — a video child _wants_ a locator, this is the whole point.
- **`CitationInstance.locator` stays one opaque string.** No structured columns (`locator_seconds`), no per-type tables. The core stores and displays a string it does not interpret; the citation type owns the grammar (validate, normalize, deep-link). This is also the isolation move — a plugin can define locator semantics without touching the schema.
- **Constraint changes**, both derived from the registry rather than hand-listed (see below): the `source_type` CHECK gains `video`, and `identifier_key_requires_web` is replaced by "identifier_key allowed only on types whose spec carries schemes" (today: web, video).
- **YouTube root and children become `source_type="video"`.** `get_or_create_scheme_child` stops hardcoding `SourceType.WEB` and mints the scheme's owning type instead.

No data migration: prod has no video-shaped rows, and dev resets to the pre-0039 snapshot.

## The citation-type plugin architecture

### What is scattered today

Per-type knowledge currently lives in at least seven places: the `EXTRACTORS` registry, the `SOURCE_TYPE_TRAITS` table, the `SourceType` and `IdentifierKey` enums, two hand-listed DB CHECK constraints (`source_type_valid`, `identifier_key_valid` — already a [model-driven-metadata](../model_driven_metadata/ModelDrivenMetadata.md) violation), the hardcoded locator placeholder in `CitationLocatorStage.svelte`, and rendering assumptions in the reference components. Adding a type today means finding all of them.

### The shape: two plugin units, layered contracts

This follows the catalog's established pattern (registry → typed spec → codegen, per [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md)), with one structural rule doing most of the work: **the type owns locator semantics; a scheme speaks only structured values.** The video type parses and normalizes `1:02:03`; a video scheme is handed a plain `start_seconds: int` and an identifier, and never sees a raw locator string. That layering is what makes a scheme small and hard to get wrong — a Vimeo author writes URL patterns and a parameter syntax, not a timestamp parser.

**Backend types — `apps/citation/citation_types/`.** One module per type (`book.py`, `magazine.py`, `web.py`, `video.py`), each exporting a typed `CitationTypeSpec`:

- the `source_type` value and display label
- the traits (absorbing today's `SourceTypeTraits` row)
- the **locator contract**: kind (`freeform` | `none` | `timestamp`), prompt/placeholder text, `validate`/`normalize` functions, and a parse to the type's structured locator value (for video: seconds)
- the **Protocol its schemes implement** — the base scheme contract plus type-specific extras (video's adds `deep_link(identifier, start_seconds) -> str`). A typed Protocol, so mypy holds a scheme author to the contract instead of a reviewer holding them to a convention.

**Backend schemes — `apps/citation/citation_types/schemes/`.** One module per scheme (`ipdb.py`, `opdb.py`, `youtube.py`, later `vimeo.py`), each exporting a spec implementing its owning type's Protocol:

- `key` (the `identifier_key` value), display label, and the owning `source_type` — what its children mint
- recognition: `extract(url) -> SchemeMatch(identifier, start_seconds | None) | None` (host-anchored patterns) and `validate_identifier(raw)` for bare ids
- `canonical_url(identifier)` — the URL every URL shape collapses to
- the owning type's extras — for video schemes, `deep_link(identifier, start_seconds)`
- `root_seed`: declarative facts about the platform root (name, homepage URL, recognition hosts). The root is still created by a data patch — a scheme is live only once its root is seeded — but the patch is authored from these facts and a conformance check asserts a seeded root matches its spec, so the spec and the DB can't silently disagree.

Both units are **pure**: declarative facts plus pure functions, no model imports, no DB access. Like today's `source_type_traits.py` they form a dependency-free leaf `models.py` imports one-way; all DB work (child minting, recognition queries, instance writes) stays in core, which consumes specs. That purity is what makes "move to another repo" and "uploaded plugin code" plausible later — a spec is data plus stateless functions, not a Django citizen.

A single registry module aggregates both: types with an import-time exhaustiveness check (the `_assert_exhaustive_traits` pattern), schemes as an explicit one-line registration each (greppable beats magic auto-discovery). Everything that today reads `EXTRACTORS`, `SOURCE_TYPE_TRAITS`, `SourceType.choices` or `IdentifierKey.choices` reads the registry instead, and both CHECK constraints derive their value lists from it — a new scheme flows into `makemigrations` instead of a hand-edit.

**Deep links are computed server-side.** Reference-rendering schemas ship the finished access URL — the deep link when a locator is present, the canonical URL otherwise — so **no per-scheme code exists in the frontend at all**. This is deliberate and is what collapses the third-party surface to exactly one Python module. The cost is negligible: deep links matter on read surfaces, which are server-fed anyway.

**Codegen + frontend — per-type only.** `make codegen` grows an export of per-type frontend metadata (alongside `entity-meta.ts`): type keys, labels, locator kind, locator prompt/placeholder. `src/lib/citation-types/` holds one hand-written module per **type** implementing a small `CitationTypeFrontend` interface — client-side locator format/validate (UX mirror of the backend grammar), locator-hint handling — aggregated in one registry map keyed by `source_type`, with an exhaustiveness assertion against the generated keys so a backend type without a frontend module fails the build, not the user. `CitationLocatorStage`, `ReferencesSection`, `CitationTooltip`, `EntitySources` consult the registry only; search results and recognition responses already carry `source_type`, so components have the lookup key. Schemes never appear on this side.

**The honest tension**: locator validation must be backend-enforced, so the frontend type module is deliberate duplication for UX (or a codegen'd regex where the grammar allows). It is confined to the type level — the rare, first-party unit — which is exactly where duplication is affordable.

### The isolation contract

The measurable end-state, stated so reviews can hold the line, at two levels matching the two audiences:

- **Adding a scheme (the third-party case): one backend module + one registry line + `makemigrations` + a seeding patch. Zero frontend code, zero core edits, zero edits to the owning type's module.** Vimeo is the acceptance test for this plan's architecture: if it needs more than that list, the seam leaked.
- **Adding a type (first-party): one backend module + one frontend module + registry entries + a codegen run.**

A grep for a type or scheme key (`"video"`, `"youtube"`) outside its module, the registries and generated output should return nothing. Core components — the models, the recognition pipeline ordering, the cite-flow state machine, the patch grammar — consume specs and never name a type or scheme.

### The scheme conformance harness

A structured interface is only as good as its enforcement, and third-party code arrives without house context — so the registry drives a **parametrized conformance suite that every registered scheme passes automatically**:

- `extract(canonical_url(id))` round-trips the identifier
- `validate_identifier` rejects junk (empty, overlong, wrong charset, embedded whitespace)
- URL patterns are host-anchored — a look-alike host (`notyoutube.com`) must not match
- `deep_link` output is a well-formed URL on the scheme's own host, for both zero and nonzero start times
- a `SchemeMatch.start_seconds` hint round-trips cleanly through the owning type's locator grammar

A new scheme enrolls in the harness just by being registered; it ships with the harness green plus its own example-based tests (real URL shapes for its platform). Reviewing a third-party scheme PR then reduces to reading one pure module and its examples. True untrusted upload — sandboxed execution of contributed code — stays out of scope; purity plus the harness is the preparation, and PR review is the trust mechanism for now.

### Interface changes rippling from the spec

- `Extractor.extract` becomes the scheme's `extract`, returning `SchemeMatch(identifier, start_seconds)` instead of a bare string; the YouTube scheme parses `t=`/`start=` params (bare seconds and `1h2m3s` unit forms) into seconds, and the **type** formats the hint to its canonical locator form. IPDB/OPDB return no hint.
- `CitationRecognitionSchema` gains a `locator_hint` field so the paste flow can seed the locator stage.
- Instance write paths (API mint, save-payload citations, patch apply) resolve the cited source's `source_type`, look up the type spec, and run its locator contract before storing.
- Reference-rendering schemas carry the **server-computed access URL** (deep link when a locator is present) wherever citation links render — the frontend renders it, never builds it.

## Unwind plan

1. **flipcommons model + registry change** (this repo): the `citation_types/` package, `SourceType.VIDEO`, the migration adding `video` to the CHECKs and replacing the identifier-key constraint, spec-driven `get_or_create_scheme_child`, locator validation on all write paths.
2. **flippatch rewrite** (sister repo): in patches ≥0039, the YouTube root's `sources:` declaration becomes `source_type: video`; existing `cite: youtube:…` entries gain `locator:` timestamps where the author knows them. Patches ≤0038 are untouched (they contain no YouTube cites).
3. **Ordering**: the flipcommons change **deploys before** rewritten patches reach R2 — a flipcommons that doesn't accept `source_type: video` can't ingest them (same deploy-before-publish rule as [CitationInstanceQuotes.md](CitationInstanceQuotes.md)'s mapping-form widening).
4. **Dev DBs**: replace `backend/db.sqlite3` with the `backend/db.pre-0039.sqlite3` snapshot, run migrations, re-ingest patches — repeatable as often as needed while iterating.

## Settled decisions

- **Human-readable canonical timestamps**, not raw seconds — the locator is displayed verbatim everywhere.
- **YouTube scheme only in v1.** Vimeo, archive.org, etc. become later scheme modules under the same video type. A video on a platform with no scheme is cited as a web page until its platform earns one — generic video URLs have no reliable dedup or deep-link story.
- **Flat hierarchy** — platform → video, no channel level, matching web flatness and keeping recognition's host-to-root resolution simple.
- **Full plugin architecture now**, not a thin traits patch — it is mostly moving existing code behind one seam, and doing it at three-going-on-four types is cheaper than at five.
- **Schemes are the primary third-party extension point**, isolated more aggressively than types: their own module directory, their own typed per-type Protocol, structured values only (never raw locator strings), and a registry-driven conformance harness. A new type is a product decision; a new platform is a drop-in.
- **Deep links are computed server-side**, precisely so a scheme has no frontend footprint — one Python module is the whole authoring surface.

## Not in this plan

- **Video title extraction.** Scheme children are named `YouTube #<id>` today; a later extraction-endpoint addition (YouTube's oEmbed endpoint returns titles without an API key) could propose real names, following the existing draft-not-auto-create extraction rule in [Citations.md](../../Citations.md).
- **Other platforms' schemes** (Vimeo, archive.org, Twitch): each is one drop-in module under `citation_types/schemes/`; none ships in v1, but Vimeo is the standing acceptance test for the isolation contract.
- **A scheme authoring guide.** The spec Protocol, the youtube module and the conformance harness double as the documentation for now; a short `docs/SchemeAuthoring.md` is worth writing when the first external contributor shows up.
- **End times / ranges**: deliberately excluded, per point-citations.
- **Moving citation types out of the repo / sandboxed execution of uploaded scheme code**: the seam this plan builds (pure specs, typed Protocols, the harness) is the prerequisite, not the deliverable.

## Prior art

Wikipedia's `{{cite AV media}}` carries a free-text `time=` parameter ("the time the event occurs in the source") — the same locator idea, but unvalidated text. We go slightly stricter with a validated grammar because we deep-link from it: a locator that renders is allowed to be sloppy; a locator that becomes a URL parameter is not.

## Phasing

1. **Backend registry refactor (pure move).** Create `citation_types/` with type specs for book/magazine/web and scheme modules for ipdb/opdb (absorbing `SOURCE_TYPE_TRAITS`, `EXTRACTORS`, the enums) plus the aggregating registry; point core readers at it; derive the CHECK value lists from it; land the registry-driven conformance harness over the existing schemes. No behavior change, no migration (the derived lists equal today's hand-listed ones), existing tests stay green.
2. **The video type + youtube scheme (backend).** `video.py` with traits, the timestamp grammar and the video-scheme Protocol; `schemes/youtube.py` recast against it with `start_seconds` extraction and the deep-link builder; the migration (CHECK gains `video`, identifier-key constraint replaced); spec-driven scheme-child minting; locator validation wired into the API and ingest write paths; reference-rendering schemas ship the server-computed access URL. Grammar and write-path validation are TDD'd; the harness enrolls youtube automatically.
3. **Frontend registry + UX.** The codegen channel; per-type `src/lib/citation-types/` modules and registry; locator stage reads type prompts and validates inline; paste flow consumes `locator_hint`; reference surfaces render the served deep links.
4. **Data unwind.** Rewrite flippatch ≥0039 (root declaration, locators on existing YouTube cites); verify by resetting to the pre-0039 snapshot and re-ingesting; deploy flipcommons before publishing rewritten patches to R2.
