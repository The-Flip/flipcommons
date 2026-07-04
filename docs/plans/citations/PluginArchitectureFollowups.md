# Citation Plugin Architecture — Follow-ups

Tracking doc for work surfaced while reviewing the citation type/scheme plugin framework on `claude/video-citation-design-lpsjpx`. Organized into streams with sequencing and dependencies. The framework itself is strong; these are refinements to typing honesty, the three-audience contract surfaces, and — the largest lever — making an individual scheme as small to build and test as possible. Companion to [VideoCitations.md](VideoCitations.md), which holds the original architecture and the rejected-platform reasoning that Stream F builds on.

## Stream A — Immediate small fixes (this branch, decided)

- **A1. Soften the `VideoSchemeSpec` enforcement docstrings.** `base.py` and `registry.py` both claim mypy statically enforces that a video scheme implements `VideoSchemeSpec`; it does not (the subclass adds no fields, so a plain `SchemeSpec(source_type=VIDEO, …)` type-checks). Restate the true mechanism — import-time `isinstance` in `_assert_registry_coherent` plus the conformance harness — and note that static enforcement arrives for free the moment the subclass carries a required field. Decided: soften, not restructure (per-type registration lists would keep the runtime check anyway, so they add machinery without removing a check).
- **A2. Fix `RecognitionChild.source_type` typing.** In `extractors.py` it is a bare `str = ""`; the `CitationSourceTypeValue` Literal and `citation_source_type()` coercer exist precisely for internal structures like this. The one internal seam where an unvalidated string rides through otherwise-typed code.

## Stream B — Recorded deferral

- **B1. Generic structured-locator value.** `base.py`'s `LocatorContract.parse_value`/`format_value`, `SchemeMatch.start_seconds` and `DeepLinkBuilder` are hardwired to `StartSeconds = int` in the supposedly type-agnostic base layer — so a future non-`int` locator value (page number, coordinates) means editing base contracts, not just adding a type module. Deliberately deferred until a second value shape actually exists (audio/podcast will reuse `int` seconds, so it may never bind). Recorded so it is a decision, not an oversight.

## Stream C — Three contract surfaces × two frameworks

The plugin system has two extension axes (first-party **types**; third-party **schemes**), and each should expose three distinct surfaces: (1) author-facing, (2) framework-facing, (3) consumer-facing. Findings, held up to that grid:

- Frontend consumer surface for **types** is excellent and distinct (codegen'd `CITATION_TYPE_META` + `CitationTypeFrontend`; the cite UI never sees a spec).
- Schemes have **no** frontend surface — deliberate and correct (deep links computed server-side).
- **Author (1) and framework (2) are conflated for schemes**: `SchemeSpec` carries both the author's input fields and the framework's driver methods (`extract`/`normalize`/`validate_identifier`) on one class. Types don't have this problem — `CitationTypeSpec` is declarative, behavior lives in `LocatorContract`.
- **Backend consumer surface (3) is unnamed and leaky for both.** A facade exists in spirit (`recognize_url`, `deep_linked_url`, `normalized_locator`, scheme-child minting) but ~6 core modules bypass it into spec fields: `parsing.py`/`api.py` call `spec.extract`, `source_upsert.py` reads `spec.root_seed`, `deep_links.py` reads `spec.deep_link`/`spec.canonical_url`. The isolation contract holds for plugin _names_ (no consumer names `youtube`/`video`) but not for _field shape_ — consumers are coupled to the spec's field vocabulary.

Governing decision: invest **asymmetrically by audience**, matching the design's own stated priority ("schemes isolated more aggressively than types"). Not three symmetric layers × two frameworks.

- **C0. Design note recording the asymmetry** (prerequisite framing): crisp three surfaces for schemes, a lighter two for types, one explicitly-named cross-framework seam. So the shape is a recorded decision before any refactor.
- **C1. Scheme consumer facade (highest decoupling value).** Designate and consolidate the backend consumer API; route the bypassers (`parsing.py`, `api.py`, `source_upsert.py`) through it instead of reaching into `SCHEME_SPECS` fields. Collapses the field-shape coupling to one seam.
- **C2. Name the scheme framework-driver surface (2).** Make `extract`/`validate_identifier`/`normalize` legible as "what the framework calls on your spec," not "what you write."
- **C3. Split the scheme package public API by audience.** Authoring exports (spec types + Protocols) vs consumer exports (registry accessors + facade); today one flat `__all__` mixes `SchemeSpec` with `citation_type_spec`.
- **C4. Name the type framework's backend consumer surface (lighter).** So `models.py` stops reaching into `.child_skips_locator`/`.parentless_abstract`/`.flat_hierarchy` directly.
- **C5. Name the cross-framework composition contract.** "Type owns the locator value; a scheme speaks only the structured value" is the most load-bearing and most implicit contract; state it in `base.py` + the design doc with `deep_linked_url` as the reference implementation.

## Stream D — Scheme implementation tightness

Simple schemes (ipdb/opdb, ~29 lines, mostly docstring) are at the floor already. The growth to 90+ lines (youtube/vimeo/tiktok) is largely irreducible platform complexity — but three _framework_ concerns are copy-pasted into every hand-written regex:

- **D1. Pattern + extractor helpers.** `anchored(host, path_re)` to compose the `https?://(?:www\.)?<host>` anchor (a contract requirement the harness checks, yet hand-rolled per scheme — a missing anchor is the `notyoutube.com` spoof); an `ID_BOUNDARY` constant for the duplicated `(?=/?(?:[?#]|$))` lookahead; `seconds_from_query(*names)` / `seconds_from_fragment(*names)` factories for the near-identical start-seconds extractors (youtube query vs vimeo fragment differ by one line). Keep a raw-regex escape hatch for genuinely weird shapes (TikTok composite, Vimeo unlisted hash) — a convenience, not a cage. Moves the security-sensitive regex plumbing behind the framework.

## Stream E — Scheme testing tightness (largest single win)

The 153-line conformance harness tests every scheme's invariants for free. But each scheme _also_ carries a hand-written test module (x 81, vimeo 97, tiktok 116 lines) that is ~70% structural boilerplate — a test class, `@pytest.mark.parametrize`, a "these URLs → the id" list, a "these junk URLs → None" list. That is data wearing a code costume. (Tell: youtube, the reference scheme, has no dedicated scheme test at all — coverage scattered across three pre-refactor files; the testing story isn't even uniform.)

- **E1. Data-driven example harness.** Schemes declare `valid_urls` / `invalid_urls` / `start_time_cases` as data (next to the spec, or an optional `examples` field the conformance suite reads); one shared parametrized harness runs them across all schemes. Per-scheme test modules shrink from ~100 lines of code toward ~30 of data; genuinely bespoke assertions (X's dual host families, handle-free canonical) stay as small extras. Also brings youtube/ipdb/opdb into uniform coverage. End state: a new scheme is one module = declarative spec + composed helpers + an example table, with the framework doing the driving _and_ the testing.

## Stream F — Source misclassification / deliverer hosts (separate product plan)

The "how do we keep classification clean" question (Amazon book/movie mis-filed as web). Its own plan; the full version depends on instance access URLs ([CitationInstanceUrls.md](CitationInstanceUrls.md)) landing, but two guardrails are doable now. Core insight (already recorded in VideoCitations.md's rejected-platforms section): Amazon is a **deliverer**, not a scheme and not a web root — the URL is the copy consulted (access), not identity; minting a web child _fabricates identity_ and fragments a work into per-platform children.

- **F1. Access-only / deliverer host recognizer** — the "fourth recognizer verb": declared hosts whose recognition outcome is "record this URL as access; identify the work separately." (post-access-URLs)
- **F2. Interactive-path guardrail (near-term, cheap).** A deliverer-host denylist in the web-create stage that replaces "Create site" with "cite the book/video itself" and hands off to the authored-work form. Converts the highest-volume misclassification into a teaching moment. The patch path is already protected (won't mint parentless web roots); the interactive path is the hole.
- **F3. Relax video `parentless_abstract` keyed on `identifier_key`** (set = platform root, abstract; blank = citable work) — the parentless-citable video work = movie shape, mirroring the book rule.
- **F4. Amazon book auto-classify (near-term).** `/dp/` ASIN is the ISBN-10 for books → route through the existing Open Library extraction to prefill a book draft — a fully automatic correct outcome for the single most likely paste.
- **F5. Provisional interactively-minted roots.** A gardening/review view ("roots created interactively, newest first"); attribution (`created_by`) already exists. Reframes the goal from prevent-all (impossible) to make-visible-and-cheap-to-repair.
- **F6. Source merge tool.** Repoint `CitationInstance` rows (PROTECT blocks deletion while cited), move links/domains, absorb the duplicate — the "citation gardening" the upsert warnings already reference as the merge backlog.
- **F7. Thread the pasted URL through as future `access_url`.** The paste flow already holds the exact string (`?t=` and all) and currently discards it after extracting identifier + hint; thread it when instance URLs land.

## Suggested sequencing

1. **A1 + A2 now** on this branch (tiny, decided). Record **B1** as a known deferral.
2. **C0 design note** — frames Streams C, D, E (all downstream of "schemes get the aggressive isolation").
3. **Scheme-tightness epic** — the coherent focused effort: **C1–C3 + D1 + E1** (facade + audience split + helpers + data-driven tests). This is where a new scheme becomes cheap. **C4/C5** ride along.
4. **Stream F** — separate product-design plan; **F2/F4** can ship as near-term guardrails independent of the rest; the structural pieces (F1/F3/F5/F6/F7) sequence after instance access URLs.

## Open decisions

- Long-term tracking: keep this in-repo doc as the backbone, or mirror the discrete items into GitHub issues? (Issues are outward-facing — not created without a go-ahead.)
- Start executing A1/A2 now, or hold until the whole organization is reviewed?
- Scheme-tightness epic: design note (C0) first, then implement — confirm.
