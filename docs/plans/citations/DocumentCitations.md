# Document citations

A manufacturer's first party documents are the absolute best, most important source materials for citations. We always cite them in preference of other sources.

IPDB has a huge trove of documents: thousands of manufacturer manuals, handbooks, parts lists, field bulletins, 3rd party game guides, and patents.

## Exploring IPDB docs

You can explore the IPDB doc trove in Pinexplore's DuckDB analytics database. Read Pinexplore's `sql/01_reference.sql` (class vocabulary, parent edges, detection patterns) and `sql/12_documents.sql` (`ipdb_documents`, `ipdb_patents`, `ipdb_trade_articles`) as a working prototype of the document schema — four independent axes (class, container, publisher, subject), a shallow is-a hierarchy where one document legitimately holds several classes, and patents and trade articles as separate source kinds — but treat its classification as coverage-measured and precision-unmeasured, and read `~/.claude/plans/pinexplore-document-classification-remaining-work.md` for what's known broken.

## Citing IPDB

However, there's a problem citing those docs from IPDB. A Williams manual on IPDB is currently classified as a web source, and web sources are identified by recognition host. The host is `ipdb.org`, therefore the source is IPDB. The model has no way to express "Williams' operations manual, held at IPDB" — the way a book citation names the publisher, not the bookshop that sold it.

The failure mode, explicitly: an `ipdb.org/files/…/manual.pdf` URL doesn't match the IPDB scheme (`/machine.cgi` only), so it falls to `_recognize_by_host` → mints a reference web child under the IPDB root (`extractors.py:571`). Three things break: publisher reads as IPDB; identity is the URL, so the same manual at `ipdb.org`, `archive.org` and `planetarypinball.com` is three sources; no room for document-level metadata.

### Fixing citations

Citation `SourceType` is currently `book | periodical | web | video` — there is no document or manual type. Should we...

- Create a new `SourceType` type?
- Widen `book` to be `document`?
- Use `periodical`?

See [citation source design](#citation-source-design).

### Prefer archive copies

We'd rather acquire and cite those docs from an archive site like archive.org and not just IPDB when possible, because we over-rely on IPDB already.

Once we have a non-web way of citing these docs, I guess we'd attach multiple URLs to the doc: archive.org, IPDB, Pinside, however many places a doc exists.

## Pre-seeding citation sources

We should consider pre-seeding all of these documents, or a selection, as sources available to be cited in Flipcommons. This would be good on its own, but also play into our [web cache trove](#web-cache-trove) and [hosting the docs](#document-library) publicly ourselves.

## Web cache trove

We want to expand Pinexplore's web cache to include this trove. Flippatch AI sessions researching data patches should be able to do one single full text search and get both the existing cached docs and this trove of docs, even before they are cached -- the search would search the names/titles/metadata of documents we haven't acquired yet.

As part of doing this, web cache should contain more structure and metadata around the docs than IPDB does; see [document classification](#document-classification) below.

As we acquire new docs NOT identified by IPDB, we'd apply the same structure and metadata.

### Document library

We want Flipcommons to publicly host all these docs at some point. See [DocumentLibrary.md](../DocumentLibrary.md).

Pinexplore's web cache would be a prototype of how to [structure it](#document-classification). The documents acquired in web cache would be placed directly into Flipcommons; we wouldn't go re-acquire those docs from the internet.

## Document classification

We can improve on IPDB's classification, structure and metadata -- and have already started, in [Pinexplore's DuckDB](#exploring-ipdb-docs).

IPDB assigns a doc to the following categories:

| category           |  files | models | sample name                                                              |
| ------------------ | -----: | -----: | ------------------------------------------------------------------------ |
| `image`            | 80,374 |  5,535 | "Image # 25474: A-B-C Bowler Ad"                                         |
| `documentation`    |  2,251 |  1,241 | "Schematic Diagram (continuous, for serial numbers below 1640)"          |
| `file`             |  1,669 |    878 | "Hi-Score Replay Adjustments - Chart"                                    |
| `rom`              |  1,173 |    487 | "U15 L-1 Sound ROM, 4MB Chip Version"                                    |
| `rule_sheet`       |    188 |    154 | "The Addams Family Rulesheet Version 2.0 (Jan/27/1995), by Brian Dominy" |
| `service_bulletin` |    133 |     76 | "Customer Service Bulletin B-A004 (undated, adding posts to playfield)"  |
| `multimedia`       |     40 |     23 | "More Game Play At Night Movie"                                          |

The taxonomy **mixes axes**:

- `image`, `rom`, `multimedia` and `file` are **formats**
- `service_bulletin` and `rule_sheet` are **document classes**. `documentation` alone lumps 2,251 files — operations manuals, operators handbooks, parts lists and platform schematics all in one bucket. And `file` is a junk drawer holding adjustment charts, promotional photos and a "Differences between TAF and TAFG" comparison sheet alike.

A finer classification already exists, as free text in the IPDB document names: "Operations Manual (English, May 1996, Final)", "Operators Handbook (May 1996)", "Parts List", "Schematic Diagram (continuous, for serial numbers below 1640)". IPDB knows each document's class, language, date, revision and even the serial-number range a schematic applies to — theu just don't give it to us as structured fields.

The `0215-frontier-2026` campaign has hit cases IPDB's shape _cannot_ express:

- **Document attached to multiple Models**: `Pokemon_LE_Pre_web.pdf` covers LE and Premium.
- **Document attached to a System**: the `WPC-95 Schematic Manual` under `TOTAN` is the same document as under every other model that uses `/systems/wpc-95`.
  - We want to attach that document to the System, not the Models. A Model shows its System's docs along with ones directly attached. However, this is not a blanket thing: while "Williams WPC-95 Schematic Manual" is platform-level, "Schematic Diagram (continuous, for serial numbers below 1640)" is specific to one machine's serial range.
  - This is not an edge case; schematics are half the trove.

### Each doc should exist exactly once

We do not want to store or show duplicate copies of the same document. It needs to exist exactly once in our system. Pokemon LE and Premium link to the same copy of `Pokemon_LE_Pre_web.pdf`. I assume we'd have some sort of content_sha detector that enforces this.

#### How small can a document class be?

Working proposal: a class with fewer than ~20 documents probably has not earned its place. Count **documents not matches**, since IPDB stores a shared document once per model, so match counts overstate. In pinexplore, twelve classes come in under 20:

`bill_of_material` 5, `installation_instructions` 6, `notice_to_operators` 7, `correspondence` 7, `packing_list` 8, `interview` 9, `photo_set` 12, `video` 14, `game_description` 14, `specification` 17, `dip_switch` 18, `cad_file` 18.

Two things make this genuinely undecidable from that trove alone:

- **The denominator is a judgement.** Counting distinct basenames over non-image files gives 17 classes under twenty; counting the whole trove gives 12, because gallery scans of flyers and instruction cards are real documents. `certificate` reads 3 one way and 37 the other; `advertisement` 4 or 71.
- **IPDB cannot distinguish a rare class from an invented one.** Feature matrices, release notes and quick-reference guides are thin in IPDB and routine in the manufacturer-site documents the flippatch campaigns work with. A vocabulary pruned on IPDB evidence would be shaped by IPDB's naming habits rather than by what documents exist.

## Citation source design

We need to determine what to do about these types of docs:

- **Manufacturer docs**
- **3rd party docs about a model**, like a gameplay strategy guide. These often have multiple versions. These sometimes have multiple authors, which change by version.
- **Patents**
- **Trade articles** (these are `periodical`, full stop)

Some observations:

- Books are ISBN-centric and these docs don't have ISBNs. While ISBN is optional (because pre-ISBN books), but a data patch `ref:` can't reference non-ISBN books because the ref is by ISBN. Since manufacturer documents don't have an ISBN, I assume we'd reference by slug, like `periodical`? Is that how we'd handle non-ISBN books too?
- Creating a separate class would permit distinct fields (manufacturer, revision, document class). How do wikidata and wikipedia model this?

---

## Proposed design

### Summary

The four kinds of document this plan has to place, and where each lands:

| scenario         | `CitationSource` type | example cite                                                                                                |
| ---------------- | --------------------- | ----------------------------------------------------------------------------------------------------------- |
| Manufacturer doc | `document` (new)      | `williams:tales-of-the-arabian-nights-operations-manual-1996` — a child of Williams, which is its publisher |
| 3rd party doc    | `web` (unchanged)     | a plain URL cite — **deferred**, with a known cost; see [§2](#third-party-guides-stay-web-for-now)          |
| Patent           | `document` (new)      | `uspto:us4373731` — a child of the issuing-office root, which is its publisher                              |
| Trade article    | `periodical`          | `coin-slot:1992-spring` plus locator `p. 21` — the **issue** is the record, the article a locator           |

So pinexplore's three `source_kind`s collapse to two flipcommons types, only one of which is new: `patent` folds into `document`, `trade_article` into `periodical`, and the third-party slice of `document` stays where it already is.

**Every document has a publisher root. There is exactly one shape.** That single constraint is what keeps this proposal small — it needs no new column, no new cite-ref form and no change to recognition.

The decisions behind that table:

- **A new `document` citation type.** Not `periodical`, not a widened `book` — the reasoning is [below](#1-document-earns-a-type).
- **One shape: publisher-rooted.** A parentless document is always a container, exactly as a parentless periodical is. Nothing is both a namespace and a work, so nothing needs disambiguating.
- **Versions and languages are siblings, not children.** Two levels is enforced today, not a choice.
- **Authorship is data** — free-text `author`, semicolon-separated — never structure.
- **No addressing changes at all.** `williams:tales-of-the-arabian-nights-operations-manual-1996` is already legal cite grammar; the parser, resolver and patch `sources:` verbs are untouched.
- **`book` and `video` are left alone.** Both carry a dormant addressing gap, and neither is in scope — see [§5](#5-addressing-nothing-changes).
- **Document class, content hashing and Model attachment are out of scope.** No citation surface consumes any of them, and a citation source carries identity and attribution only — see [§9](#9-what-this-design-deliberately-excludes).

### 1. `document` earns a type

[MovieCitations.md](MovieCitations.md) set the bar: a candidate earns a citation type only when it **behaves** differently, not when it merely **reads** differently. A `CitationTypeSpec` declares five behavioral facts. Run a manufacturer manual down them:

| fact                             | book         | web          | periodical | document                                   |
| -------------------------------- | ------------ | ------------ | ---------- | ------------------------------------------ |
| `flat_hierarchy`                 | no           | yes          | no         | no                                         |
| `schemeless_parentless_abstract` | False        | True         | True       | **True** — a publisher root is a container |
| `child_skips_locator`            | False        | True         | False      | False — cite a page/section                |
| `slug_addressed`                 | False (ISBN) | False (host) | True       | True — no natural identifier               |
| locator                          | freeform     | freeform     | freeform   | freeform                                   |

On the flags alone a document is close to `periodical`, and the movie rule would say "not a new type." **The movie rule does not reach here**, because it rests on a containment that does not hold: a movie _is_ a video, so `video` is merely the less specific label. **A Williams manual is not a periodical in any sense.** Filing it there is a falsehood a contributor reads in a dropdown, and [CitationsDesign.md](CitationsDesign.md) lists reader rendering and edit fields among the type axis's declared jobs — which is precisely where the two diverge ("Williams, _Tales of the Arabian Nights Operations Manual_, May 1996" vs. "Billboard, 1945-09-29, p. 42").

Not `book`: books are ISBN-addressed and a manufacturer is not a book root.

**The cost is contained but larger than "one module."** The profile is freeform plus slug-addressed, so no new grammar is needed — but a type is a first-party product concept and several surfaces enumerate the type set by hand. The full list:

| surface                                                 | change                                                                                                                                                            |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `citation_types/document.py`                            | the new spec, ~12 lines                                                                                                                                           |
| `citation_types/registry.py`                            | one entry in `_CITATION_TYPES`                                                                                                                                    |
| `citation_types/vocabulary.py`                          | `SourceType.DOCUMENT` **and** the `CitationSourceTypeValue` Literal — an import-time assertion fails if the hand-mirrored Literal drifts                          |
| migration                                               | the `source_type` CHECK derives from `SourceType.values`, so `makemigrations` picks it up                                                                         |
| `schemas.py` — `CitationSourceCreateSchema.source_type` | today a hardcoded `Literal["book", "periodical", "video"]`, plus its description text                                                                             |
| `CitationCreateStage.svelte`                            | the `SourceType` union and the default fallback — but **not** the radio list (see below)                                                                          |
| `citation-types/index.ts`                               | one registry line, `document: freeformType`                                                                                                                       |
| `CitationIdentifyBySearchStage.svelte`                  | copy is a binary `isWeb ? pages : editions` (`:49`, `:51`, `:272`) — a document root would read "Filter editions…"; needs document wording and a test             |
| `make codegen`                                          | regenerates `CITATION_TYPE_META` and the `CitationTypeKey` union                                                                                                  |
| [DataPatches.md](../../DataPatches.md)                  | the `sources:` `source_type` list and the slug-addressed section — **docs only**; the patch parser validates against `SourceType.values` and needs no code change |
| `api.py` — `search_citation_sources`                    | add `Q(slug__icontains=q)` to the text filter (see below)                                                                                                         |
| `planning.py` / `source_upsert.py`                      | track same-patch declared roots as `(source_type, slug)`, not bare slugs (see below)                                                                              |

**`document` must stay out of the interactive root picker.** The type picker shows only when creating a **root** (`showTypePicker = seed.kind === 'name' && !parentContext`, [CitationCreateStage.svelte:76](../../../frontend/src/lib/components/input/citation/CitationCreateStage.svelte)). Offering `document` there would let a contributor who searched "Tales of the Arabian Nights Operations Manual" and found nothing create a **parentless document** — an abstract publisher root wearing a manual's name. Publisher roots are seeded by patch, so interactive root creation is not wanted: add `document` to the `SourceType` union and the fallback so a **child** created under a `parentContext` type-checks, and leave the radio list alone.

**A document created interactively cannot carry its URL yet.** `CitationSourceCreateSchema` forbids link fields (`extra="forbid"`, no `url`), and **no frontend calls a source-links endpoint at all**, so a hand-created document has no way to be inspected. The pre-seed path is unaffected — patch `sources:` nodes carry `links:` — so this bites only interactive creation. Recorded as a known limitation rather than solved here; a link-management UI is its own piece of work.

**Same-patch root resolution is not type-safe, and adding a second slug-addressed type is what makes it reachable.** `declared_root_slugs` is a frozenset of bare slugs ([planning.py:900](../../../backend/apps/claim_ingest/patches/planning.py)); read-phase validation applies the `source_type` filter on the **DB** branch but not on the same-patch branch ([source_upsert.py:449](../../../backend/apps/citation/source_upsert.py)); and apply-side then filters `(slug, source_type)` and **silently skips the node — "skipped the node (no writes)"** ([source_upsert.py:701](../../../backend/apps/citation/source_upsert.py)). So a document child naming a same-patch _periodical_ root would validate clean and then vanish at apply. This is unreachable today only because periodical is the sole slug-addressed type. Track the pairs, and cover it with a test — the silent skip is what makes it worth fixing rather than noting.

**Search must cover `slug`.** Today the filter is `name` / `author` / `publisher` / `isbn` / `links__url` ([api.py:287](../../../backend/apps/citation/api.py)) — **not `slug`** — which this plan makes untenable, because it turns the slug into the primary handle for thousands of new rows. Concretely: `us4373731` is a patent's slug and its cite ref, and typing it finds nothing; typing `4373731` misses "US 4,373,731" on the commas. One `Q` term fixes it, and every slug-addressed type benefits — typing a periodical's slug finds it too.

**No new UI is needed to choose a publisher root.** The create flow already covers it: the contributor searches the abstract root, the flow routes to child-identification under it, and `parentContext` carries the parent into the create stage — which also hides the type picker and inherits the parent's type ([CitationCreateStage.svelte:76](../../../frontend/src/lib/components/input/citation/CitationCreateStage.svelte), [:136](../../../frontend/src/lib/components/input/citation/CitationCreateStage.svelte)). Typing "Williams" or "USPTO" works exactly the way typing "Billboard" does today, so neither the ~40 manufacturer roots nor the patent offices need a bespoke picker.

What genuinely needs **no** change, and is the reason this stays contained: the `<root-slug>:<child-slug>` cite grammar (parser, `get_slug_source`), the two-level `clean()` guards, the `sources:` block's `slug`/`parent` verbs, and URL recognition — all type-agnostic already. The registry-parametrized type-conformance harness picks the new type up automatically, so its locator grammar is tested the moment it registers.

**`document` is not "manufacturer document."** It is _a discrete published document, addressed by publisher plus slug_. Manufacturers dominate the population but do not define the type — the USPTO qualifies for the same reason Williams does, and so does a versioned third-party rulesheet.

### 2. One shape: every document has a publisher root

The root's job is mechanical: a single-valued, stable namespace that scopes child slugs. It is the **publisher** — the body that issued the document.

```text
Williams  (document root, slug: williams — abstract, a container)
  ├── Tales of the Arabian Nights Operations Manual, May 1996   (slug: tales-of-the-arabian-nights-operations-manual-1996)
  │     ├── reference → planetarypinball.com/….pdf
  │     ├── catalog   → ipdb.org/files/2570/….pdf
  │     └── archive   → web.archive.org/….pdf
  └── WPC-95 Schematic Manual                                    (slug: wpc-95-schematic-manual)

USPTO  (document root, slug: uspto)
  └── US 4,373,731 [Ball rolling game…]                          (slug: us4373731)
```

`document.schemeless_parentless_abstract = True`, exactly as `periodical` has it. A parentless document is **always** a container; a document you cite is **always** a child.

**Why not also allow a standalone, parentless document** (a work no body published)? It was proposed and rejected, because it makes a parentless row ambiguous — sometimes a namespace, sometimes a work — and nothing in the model can tell them apart:

- `is_abstract`'s only discriminator is `has_children`, so a **publisher root with no documents yet would read as citable**. That is not a corner case: the [roots-first rollout](#recommended-scope) seeds ~40 empty roots, and a manufacturer registered before its documents arrive is a legitimate long-term state. (This differs from `book`, where a childless root genuinely _is_ the work — Williams is never a document.)
- Recognition would silently skip it. `_recognize_by_child_link` and `get_or_create_web_source` both filter `parent__isnull=False` ([extractors.py:176](../../../backend/apps/citation/extractors.py), [:624](../../../backend/apps/citation/extractors.py)) — the children-only test is a stand-in for "not abstract" — so a parentless document's links would be ignored and its URL would still mint an IPDB web child.

Both would need a persistent container/work marker: a new column plus a refactor of two recognition paths that the web and scheme flows also depend on. One shape avoids all of it, which is why the third-party corpus is deferred rather than modelled with a second shape.

#### Naming and slugs

Settled conventions, applying to every document, seeded or hand-created.

**A slug is a frozen creation-time handle, not a description of the document.** This is the existing doctrine for periodical slugs ([Citations.md](../../Citations.md): slugs are "never parsed — an issue's `year`/`month`/`day` carry its date, the slug only addresses"), and documents inherit it unchanged. It matters more here because a document slug is _built from_ facts that can later turn out wrong — a Model slug can be corrected, a class misread, a date misparsed. **None of those corrections rename the handle.** Fix the fields; the slug keeps whatever it was minted with.

The reason is stronger than tidiness: patches are **append-only and replayable** — applied files are never rewritten, and a fresh database replays every historical patch. So renaming a slug does not merely orphan a reference, it breaks the replay of patches that already cite it. If a handle ever must change, it needs a backward-compatible alias, which nothing in the model supports today — which is exactly why the handle is frozen instead.

**A slug addresses; it never relates.** Slugs appear in exactly two places — a patch cite ref (`williams:…`) and the `sources:` block's `parent:` verb — and both are **wire formats resolved to a row at apply time**. Nothing stores a slug as a pointer. Every relationship this design uses is an existing `ForeignKey` to a primary key, and the whole citation app already holds that line: `CitationSource.parent`, `CitationSourceLink.citation_source`, `CitationSourceRootDomain.source` and `CitationInstance.citation_source` are all FKs, with no slug- or name-keyed reference anywhere. A document is a child of its publisher by `parent_id`, exactly as a periodical issue is. Adding a `parent_slug` column, or joining on a slug or a name, would be a regression — including for the same-patch `(source_type, slug)` bookkeeping in [§1](#1-document-earns-a-type), which is in-memory validation state during parsing and never reaches the database.

- **A publisher root's slug is the catalog `Manufacturer` slug, verbatim** — `williams`, `bally`, `data-east`. Those already exist in exactly the right shape across 760 manufacturers, so cite refs read `williams:…` and no separate vocabulary is invented. Publishers that are not manufacturers (`uspto`, a venue) mint a slug in the same grammar. **This is a naming convention and nothing more — never a join key.** Matching strings must not become a lookup: a document root is not related to a `Manufacturer` row in the database, and if that link is ever wanted it is an ordinary `ForeignKey` to the manufacturer's primary key. The convention's only benefit is that such an FK would later land on already-agreeing names instead of a reconciliation.
- **A document's slug uses the full Model slug — no abbreviations.** `tales-of-the-arabian-nights-operations-manual-1996`, never `totan-…`. Longer, but guessable by anyone who knows the game and greppable across patches; an abbreviation is knowledge you either have or you don't.
- **A document's name leads with the Model, carries its class, and parenthesises the date** — "Tales of the Arabian Nights Operations Manual (May 1996)". A platform document drops the Model and leads with the publisher instead — "Williams WPC-95 Schematic Manual". The reason is that a name is what a reader sees in a references list, where it has to identify the document unaided. It is **not** enough to make one-shot search find it — see [how documents are actually found](#finding-a-document).

#### Finding a document

**Search does not tokenize.** The filter is `Q(name__icontains=q)` on the whole query string, so only a contiguous substring matches. `medieval madness` finds "Medieval Madness Operations Manual"; **`medieval madness manual` finds nothing**, because those words are not adjacent in the name. Neither does `williams manual` find anything — no document's name contains that string, and the Williams root is named "Williams".

**The path that works is the two-stage one, and it already exists.** A publisher root is abstract, so selecting it routes the picker to child-identification, and `list_citation_source_children` filters that root's documents by name — bounded to 20, `[]` on an empty query ([api.py:636](../../../backend/apps/citation/api.py)). So: type `Williams`, pick the root, then filter within it. This is exactly how a periodical issue is found today, and it is what makes ~1,000 documents under one root navigable at all.

Two consequences for the implementation list: the child stage's copy is hardcoded to `pages` vs. `editions` and needs a document wording (see [§1](#1-document-earns-a-type)); and tokenized or parent-aware search stays an [open question](#open-questions) rather than a requirement, because the two-stage path does not need it.

#### Third-party guides stay `web` for now

Rulesheets and strategy guides **are** documents by the same test everything else here rests on, and the corpus proves it twice: they are **mirrored** (IPDB, an archive, the author's own page), and **89 of 188 IPDB rulesheets carry a version number**. You cannot version a URL. A versioned, dated, mirrored artifact has identity separable from location.

They are nonetheless left as `web` citations, deliberately:

- **We are unlikely to cite them.** They back gameplay and rules commentary; the catalog facts patches actually assert — dimensions, credits, feature counts — come from first-party manuals.
- **Structuring them does not depend on this.** Pinexplore's [web cache](#web-cache-trove) can register, classify and full-text-search the corpus with no flipcommons citation type involved. That was the main reason to want them as documents, and it does not hold.
- **The corpus is under-understood.** Its classification precision is unmeasured, and whether the right root is a venue (rec.games.pinball, Tilt Forums, PAPA) or something else is undecided. Waiting buys real information.

**The accepted cost, stated plainly: a rulesheet cited from IPDB is attributed to IPDB** — the exact problem this document opens with, knowingly tolerated for this one slice. The debt is bounded by the first bullet: promoting a `web` child later means repointing its `CitationInstance` rows under `PROTECT` with merge tooling that is unbuilt, but **no instances accumulate if nobody cites them**. A cheap signal that it has stopped being moot: web children under the IPDB root whose URL is a `/files/` PDF. If that count climbs, documents are being cited through the wrong door.

When it does come due, the choice is between a venue root (no discriminator problem, ever) and the standalone shape (which pays the column and refactor above). That decision is better made with the corpus in hand.

#### The evidence: publishers and authors are named differently

The corpus names first- and third-party documents by different conventions, which is the cleanest evidence that they are different things — and what makes the first-party slice safe to seed while the third-party slice is not. Publisher-prefix coverage in IPDB filenames:

| class                |  docs | filename names a publisher |
| -------------------- | ----: | -------------------------- |
| `handbook`           |    37 | **100%**                   |
| `press_release`      |    58 | 97%                        |
| `service_bulletin`   |   160 | 94%                        |
| `operations_manual`  |   174 | 93%                        |
| `schematic`          | 1,115 | 86%                        |
| `manual`             | 1,008 | 84%                        |
| `instruction_card`   |   241 | 75%                        |
| **`strategy_guide`** |   211 | **18%**                    |

And the 18% is very likely the _Model's_ manufacturer leaking in, not the guide's author. Third-party guides use the other grammar instead: **156 of 188 rulesheets name a person** ("The Addams Family Rulesheet Version 2.0 (Jan/27/1995), by Brian Dominy"). First-party documents are addressed by publisher; third-party guides by author.

### 3. Versions and languages are siblings, not children

Two levels is **enforced, not chosen**. `clean()` rejects a slug-addressed grandchild ([models.py:472](../../../backend/apps/citation/models.py)), and `get_slug_source` refuses any hit that has children — _"a container with children — cite the specific child"_ ([extractors.py:735](../../../backend/apps/citation/extractors.py)). A document therefore cannot carry version children without changing both.

So revisions and translations are siblings with distinct slugs:

```text
williams:wpc-schematic-manual-1992
williams:wpc-schematic-manual-1997
williams:totan-operations-manual-en
williams:totan-operations-manual-de
```

The data agrees. Only **109 of 1,192** same-title families have two or more dated members, so a date orders the revision chain 9% of the time — an edition model would be machinery for a case that is mostly unorderable anyway. And the language axis is siblings by nature: "English Manual" ×145 and "German Manual" ×18 under one title are different documents, not editions of one. Dates live in `year`/`month`/`day`; the 105 documents IPDB marks explicitly "undated" go in `date_note`, which is curator knowledge and distinct from a parse failure.

### 4. Authorship is data, never structure

Multiple authors — and authorship that changes between versions — is what **rules out author-as-root**. A root is single-valued; an author list is not, so a two-author document would either have to pick one author or exist under both roots, which is structural fragmentation worse than the mirroring problem being fixed. The arithmetic condemns it independently: **97 distinct authors across 156 authored rulesheets**, an average of 1.6 documents per would-be root.

The answer is already settled in this codebase. [MovieCitations.md](MovieCitations.md) decided exactly this for film credits: free-text `author`, semicolon-separated, role in parentheses where it is not self-evident — matching Wikipedia's `people=`, APA and Chicago — with a structured contributor table explicitly YAGNI'd until some surface needs to _query_ credits.

Same answer here: `author: "Brian Dominy; Jim Hoxsey"`. It is rare regardless — only **5 of 188** rulesheets are multi-author.

### 5. Addressing: nothing changes

Because every document is a child of a publisher root, the existing cite grammar already reaches it:

```yaml
cite: williams:tales-of-the-arabian-nights-operations-manual-1996 # the existing two-segment form
```

`_parse_cite`, `get_slug_source` and the `sources:` block's `slug`/`parent` verbs are **untouched** — no new ref form, no parser change, no resolver change. This is the single largest saving from the one-shape decision: the earlier draft of this plan needed a bare-slug ref form purely to reach standalone documents.

#### `book` and `video` have a dormant gap; neither is in scope

Both types can hold a **citable work with no address**: a parentless, childless, schemeless source that `_parse_cite`'s four forms cannot reach. Interactive citation is unaffected either way — the cite picker cites **by primary key**, so this is patch-only.

**Books.** The tempting move is `slug_addressed = True` on `book`. Rejected: that flag means "root **and child** addressed by slug", and the child half is what triggers the two-level `clean()` guard — so books would lose unbounded nesting, contradicting [Citations.md](../../Citations.md). Books do not need the child half at all, because **children carry ISBNs**; only a work-grouping root lacks an address. Getting just that would need a third addressing state (`none` / `root_only` / `root_and_child`), which is more machinery than the present need justifies.

**Books.** The tempting move is `slug_addressed = True` on `book`. Rejected: that flag means "root **and child** addressed by slug", and the child half is what triggers the two-level `clean()` guard — so books would lose unbounded nesting, contradicting [Citations.md](../../Citations.md). Books do not need the child half at all, because **children carry ISBNs**; only a work-grouping root lacks an address. Getting just that would need a third addressing state (`none` / `root_only` / `root_and_child`), which is more machinery than the present need justifies.

And the need is genuinely absent. Verified against the DB — **every non-ISBN book is an abstract container**, which `get_isbn_source` refuses to cite anyway:

| book population                                |  rows |
| ---------------------------------------------- | ----: |
| With an ISBN                                   |    27 |
| Without an ISBN, but a container with children | **5** |
| **Without an ISBN and citable (a leaf)**       | **0** |
| Children without an ISBN                       |     0 |

So the non-ISBN book hole is **prospective, not present**. It bites the day someone seeds a pre-ISBN citable book — a 1930s trade catalogue, a self-published work — which pinball history has plenty of.

This is also why volumes, editions, formats and translations need no extra depth: they are **already siblings** in the seeded data, each with its own ISBN.

```text
The Encyclopedia of Pinball          (no ISBN — the work)
  ├── Vol. 1: Whiffle to Rocket      isbn 9781889933009
  └── Vol. 2: Contact to Bumper      isbn 9781889933023
Pinball!                             (no ISBN — the work)
  ├── Pinball!, hardcover            isbn 9780525179757
  └── Pinball!, paperback            isbn 9780525474814
```

That is what an ISBN _is_ — one per manifestation. FRBR's Work → Expression → Manifestation collapses to two levels here because a manifestation implies its expression, so "Vol. 2, 2nd ed., German, paperback" is one ISBN and one leaf, disambiguated in its **name**. There is no manifestation the shape cannot reach.

**Movies.** 15 schemeless video roots are seeded, citable interactively and unciteable from a patch — the same dormant gap. `video` cannot simply become slug-addressed either: the `clean()` guard rejecting a slug-addressed child under a scheme root would invalidate **every** YouTube child.

**Neither is made worse by this plan, and neither is blocked by it.** When one comes due it needs a way to address a parentless work — the third addressing state for `book`, and for `video` that plus the slug-required CHECK relaxed to "required unless the row carries another address (`isbn` or `identifier`)" and the scheme-root guard restructured. No backfill in either case.

One caveat worth naming rather than discovering later: **do not use `flat_hierarchy` as the depth control.** It does not mean "two levels" — it means "children are minted from URLs or identifiers, never authored" ([api.py:338](../../../backend/apps/citation/api.py)), so setting it on a type with authored children would forbid authoring them.

### 6. Patents

A patent is a document whose publisher is the issuing office and whose slug is its number: `uspto:us4373731`, `epo:…`. Zero new machinery, and the cite ref reads as the patent number does.

**Deliberately not a scheme.** A Google Patents scheme would key identity on `patents.google.com/patent/US4373731A/en` — enshrining _access_ as identity, which is precisely the error [CitationSourceMisclassification.md](CitationSourceMisclassification.md) rejects for Amazon. Google Patents is a **deliverer** of patents. Jurisdiction and number are the identity, and publisher-root plus slug carries that pair exactly.

pinexplore models `patent` as its own `source_kind` because its analytics needed a different identity key (jurisdiction + number rather than basename). That is an analytics concern; the root/slug shape carries the same pair here without a third kind. IPDB holds only **49 distinct patents** anyway — the real corpus is external.

**The issuing-office roots must be seeded explicitly** — they do not fall out of the [pre-seed](#recommended-scope). That seed derives its roots from `publisher_prefix`, which parses _manufacturer_ names from IPDB filenames; on patents that field is only 33% populated and names the **Model's** manufacturer, not the office. Without the roots, every `uspto:…` ref above fails to resolve.

The scale is small: IPDB's 49 distinct patents are **US 46, ES 2, GB 1**, so three roots cover the whole set and the external corpus is overwhelmingly US. Further offices are one `sources:` node each, added on demand — there is no office registry to build and no per-office UI, since a patent is reached by searching its office root like any other publisher.

### 7. Trade articles

`periodical`, unchanged: Coin Slot, RePlay, Play Meter and Der Automat become periodical roots, issues become slug-addressed children, an article is cited as its issue plus a page locator. pinexplore's `trade_article` kind is an artifact of reading IPDB filenames, not a modeling need — stated explicitly so nobody builds a third kind. Its whole IPDB population is **26 files**.

**A known limitation, inherited rather than introduced.** Citing an article as issue-plus-locator gives its title, author and URLs nowhere to live, and two articles in one issue share a `CitationSource` distinguished only by their instances' locators. This is the existing rule for _every_ periodical ([Citations.md](../../Citations.md): "A periodical is enforced at exactly two levels (an article is cited as its issue plus a page locator)"), not something trade articles introduce. Giving articles their own identity means restructuring periodical hierarchy for all publications and migrating the existing issue children — a periodical-plan change, deliberately not attempted here.

### 8. Multiple URLs, and preferring archive copies

**Holding many URLs is free; preferring one of them is not.** `CitationSourceLink` is 0..n and typed — `reference` for the manufacturer's own copy, `catalog` for the IPDB file URL, `archive` for the archive.org snapshot, `publisher` for the manufacturer's landing page — so the model needs no change to carry every copy of a document.

**Preferring the archive copy is a seeding convention, not a code change.** `citationLinkDisplay` promotes the `reference` link to the hyperlink on the source name and renders the rest as chips ([citation-links.ts:42](../../../frontend/src/lib/components/citation/citation-links.ts)). So the preference is expressed by **which URL we type `reference`**: seed the archive copy as `reference` and IPDB's as `catalog`, and the reader lands on the archive. Per document, under our control, with nothing to build.

What is _not_ covered, and is not in this plan: **recording which copy a contributor actually consulted.** That is per-citation rather than per-source, so it needs instance access URLs ([CitationInstanceUrls.md](CitationInstanceUrls.md)).

The over-reliance on IPDB is fixed by the type change itself: **ipdb.org stops being the identity and becomes a `catalog` link.**

This also buys correct paste recognition for free, which is the strongest practical argument for pre-seeding. `_recognize_by_child_link` matches an exact child link URL, is **type-agnostic**, and runs **before** the host recognizer. So once a document carries its ipdb.org URL as a link, pasting that URL resolves to the Williams manual instead of minting an IPDB web child — in the interactive picker and on the patch path alike (`get_or_create_web_source` checks exact child links first).

This works **only because every document is a child** ([§2](#2-one-shape-every-document-has-a-publisher-root)). Both code paths filter `parent__isnull=False`, so a parentless document would be skipped and its URL would still mint an IPDB web child.

### 9. What this design deliberately excludes

A citation source carries **identity and attribution** and nothing else. These belong to whatever eventually structures and hosts the documents themselves, so nothing here blocks on them:

- **`document_class`.** No citation surface consumes it, it is multi-valued (a "Schematic Manual" is genuinely both), and it carries the unmeasured-precision problem plus the still-open ["how small can a class be?"](#how-small-can-a-document-class-be) question. Leaving it out means the citation work does not wait on the vocabulary, and a cite picker that later wants "manuals only" can filter through whatever holds the class rather than duplicating it here.
- **Content hashing / ["each doc exists exactly once"](#each-doc-should-exist-exactly-once).** Without the bytes we cannot hash, and a citation source never holds them. For citations the dedup key is (root, slug). pinexplore already measured that a filename-derived identity distinguishes 46 fewer things than plain `file_url` across 85,828 rows, and buys that by asserting merges filenames cannot support.
- **Attaching documents to Models and Systems.** A claim-controlled catalog fact, so it needs provenance and edit history — which a citation source deliberately does not have ([CitationDecisions.md](CitationDecisions.md): citations are evidence, not provenance).

Genuinely out of scope:

- **Third-party guides as documents** — [§2](#third-party-guides-stay-web-for-now). They stay `web` citations, with the attribution cost recorded.
- **A standalone (parentless) document shape** — [§2](#2-one-shape-every-document-has-a-publisher-root). It would need a persistent container/work marker and a recognition refactor; one shape avoids both.
- **Article-level identity for periodicals** — [§7](#7-trade-articles), an inherited limitation, not one introduced here.
- **Revision/edition chains and a language axis** — [§3](#3-versions-and-languages-are-siblings-not-children) makes both siblings.
- **Any change to `book` or `video`** — [§5](#book-and-video-have-a-dormant-gap-neither-is-in-scope). Their dormant addressing gaps stay dormant; nothing here makes either worse.

## Pre-seeding the IPDB trove

### What is actually there

Measured against pinexplore's `explore.duckdb`:

- **5,454 non-image files, 5,364 distinct basenames.** Cross-model sharing is far rarer than assumed above: only ~20 basenames are referenced by more than one Model. The WPC-95 schematic's 14 is the outlier, not the pattern.
- **3,628 PDFs**; 1,164 are ROM sets (not citable documents).
- **`publisher_prefix` parses on 3,875 of 5,454 (71%)**, dominated by Williams 1,077, Bally 991 and Stern 694 — roughly 40 publisher roots covers the trove.

### Recommended scope

**Roots first.** ~40 publisher `document` roots, hand-reviewable, immediately useful — every subsequent document cite becomes resolvable, and this alone is worth shipping. Add the **issuing-office roots** (`uspto`, plus `epo`/`gb` as needed) by hand in the same pass: they are not derivable from `publisher_prefix`, so without them no patent cite resolves ([§6](#6-patents)).

**Then a bounded high-confidence slice**: only classes at 84–100% publisher-prefix coverage (`manual`, `operations_manual`, `service_manual`, `handbook`, `schematic`, `parts_list`, `service_bulletin`, `instruction_card`). **Exclude `strategy_guide` and the `rule_sheet` category outright** — at 18% publisher signal we would be inventing an issuing body for ~200 documents. Those stay `web` citations ([§2](#third-party-guides-stay-web-for-now)); they want author extraction rather than publisher extraction, which is separate work.

Nothing in the seed needs `document_class`, which is what lets it ship ahead of the vocabulary question ([§9](#9-what-this-design-deliberately-excludes)).

### Two tensions to accept explicitly

- **Slugs are authored, never minted — deliberately.** Seeding thousands of documents means machine-generating their slugs from IPDB display names. This is a real relaxation of a stated principle. It is defensible — the rule exists so that a cite of an _undeclared_ slug fails loudly, and generated-at-seed-time slugs are still declared in a patch — but it needs a stable, legible, per-root-deduped generator (`tales-of-the-arabian-nights-operations-manual-1996`, not a hash — see [Naming and slugs](#naming-and-slugs)).
- **The metadata is regex-parsed and unverified.** Citation sources are not claims-controlled, so seeded publishers and dates land with no provenance and no audit trail. This is the strongest argument for the staged scope above rather than one 5,000-row import.

One trap to avoid, already measured: **`filename_year` is the Model's year, not the document's.** Of 4,203 basenames carrying a year, 3,155 exactly equal the Model's pindata year. Document dates live in the display name and nowhere else.

## Open questions

- **Two roots per organization.** Williams, Stern, PAPA and Planetary Pinball would each carry a `web` site root **and** a `document` publisher root, since same-type nesting is enforced in `clean()`. Acceptable, but worth confirming before it multiplies across ~40 manufacturers.
- **Should a `document` root carry a `ForeignKey` to the catalog `Manufacturer`?** Out of scope here — today the two are related only by a shared slug convention, which is deliberately [not a join key](#naming-and-slugs). If the link is wanted, it is an FK to the manufacturer's primary key, and the matching slugs mean no reconciliation first.
- **Tokenized or parent-aware search.** Not required — the two-stage path covers finding a document ([§2](#finding-a-document)) — but top-level search stays literal-substring, so a multi-word query spanning the publisher and the document (`williams manual`) returns nothing rather than a useful list. Worth revisiting if contributors reach for one-shot search anyway; it would mean tokenizing the query and matching the parent's name, not just a bigger cap.
- **When third-party guides earn a citation shape** — [§2](#third-party-guides-stay-web-for-now). Triggers: the seed widens past the first-party classes, someone actually needs to cite a guide, or those documents start being hosted and structured in their own right. The open sub-question is venue root vs. standalone shape.
- **When (not whether) to close the `book` and `video` addressing gaps** — [§5](#book-and-video-have-a-dormant-gap-neither-is-in-scope). The trigger for books is the first pre-ISBN citable work someone wants to seed, and for movies the first patch that wants to cite one.

## Documents to update

[Citations.md](../../Citations.md) (the type roster and the addressing forms — the book-hierarchy claim is unaffected, since `book` is untouched) and [DataPatches.md](../../DataPatches.md) (the `cite:` ref grammar, the `sources:` block's `source_type` list and the slug-addressed section, which today names periodical as the only such type).
