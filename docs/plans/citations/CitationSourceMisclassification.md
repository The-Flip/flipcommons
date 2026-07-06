# Citation Source Misclassification and Deliverer Hosts

Product plan for keeping citation-source classification clean — the Amazon book/movie mis-filed-as-web problem. The near-term slice (F2 guardrail, F4 auto-classify, and the interactive movie-create gap they expose) is specified and designed below; the structural pieces (F1/F5/F6/F7) still depend on instance access URLs ([CitationInstanceUrls.md](CitationInstanceUrls.md)) landing. The plugin architecture this builds on is in [CitationPluginSystem.md](CitationPluginSystem.md).

## Core insight

Amazon is a **deliverer**, not a scheme and not a web root — an Amazon URL is the copy consulted (access), not the identity of the work. Minting a web child for it _fabricates identity_ and fragments one work into per-platform children. The rejected-platform reasoning is recorded in [VideoCitations.md](VideoCitations.md)'s rejected-platforms section.

## Status

- **Built: F2 + F4 + movie create + ISBN-anywhere** (this plan's near-term slice, pending the prod-clone rehearsal below). The classification spine lives in `extractors.classify_url`; the deliverer table in `apps/citation/deliverers.py`; the guardrails in `api.py` (`cite-url`, `pages/`, search suppression), `url_extraction.py` (the notice + ISBN auto-classify with page-metadata fallback) and `CitationSourceRootDomain.clean()`; the movie create in the authored-work form + create endpoint (video roots only, derived from `flat_hierarchy`); ISBN-anywhere in `classify_input` / `isbnFromQuery`.
- **Shipped earlier: F3.** `CitationSource.is_abstract` keys parentless abstractness on `identifier_key` (set = platform root, abstract; blank = citable work) via the per-type `schemeless_parentless_abstract` flag — the movie shape from [MovieCitations.md](MovieCitations.md).
- **Already protected: the patch path.** `get_or_create_web_source` refuses to mint a parentless web root for an unrecognized host, so a patch cannot create an Amazon site by accident.
- **The hole this closed: the interactive path.** `cite-url` happily created a root + recognition domain for any host that cleared the DNS/public-suffix funnel, and `extract_url` scraped the Amazon page's `og:title` into a plausible-looking web draft — the flow actively encouraged the misclassification.

## Work items

- **F1. Access-only / deliverer host recognizer** — the "fourth recognizer verb": declared hosts whose recognition outcome is "record this URL as access; identify the work separately." (post-access-URLs; consumes the F2 deliverer table and the F2 classification result rather than replacing them)
- **F2. Interactive-path guardrail** — **built** (see Status). A declared deliverer table plus a URL **classification** result that every interactive surface switches on, turning "Create site" for a deliverer URL into a teaching moment plus a handoff to the authored-work form.
- **F3. Relax video `parentless_abstract` keyed on `identifier_key`** — **shipped** (see Status).
- **F4. Deliverer ISBN auto-classify** — **built** (see Status). A deliverer URL that embeds the work's ISBN (Amazon `/dp/`, B&N `?ean=`) routes through the existing Open Library extraction to prefill a book draft — a fully automatic correct outcome for the single most likely paste.
- **F5. Provisional interactively-minted roots.** A gardening/review view ("roots created interactively, newest first"); attribution (`created_by`) already exists. Reframes the goal from prevent-all (impossible) to make-visible-and-cheap-to-repair.
- **F6. Source merge tool.** Repoint `CitationInstance` rows (PROTECT blocks deletion while cited), move links/domains, absorb the duplicate — the "citation gardening" the upsert warnings already reference as the merge backlog. Also the repair path for deliverer roots/children that already exist in prod data (the guardrail stops new ones; it deliberately leaves existing rows alone).
- **F7. Thread the pasted URL through as future `access_url`.** The paste flow already holds the exact string (`?t=` and all) and currently discards it after extracting identifier + hint; thread it when instance URLs land. The F2 deliverer handoff already carries the pasted URL in flow state (unused) as the hedge for this.

## Where this sits in the architecture

The deliverer table is a **separate declared table, sibling to the two existing recognition inputs** — deliberately neither of the things it superficially resembles:

- **Not more info on root citation sources / `CitationSourceRootDomain`.** Those are positive declarations ("URLs under this host belong to this root — resolve and mint children here"), each presupposing a root source that owns them. A deliverer is the negation: "no citation source may ever exist for this host." Modeling the negation as a flagged root source would represent the thing whose nonexistence is the invariant, force every read path (search, listers, `is_abstract`, recognition) to filter it forever, and make the guardrail depend on seeding — paste an Amazon URL into a fresh DB and the guard silently isn't there. Prod's accidental `amazon.com` root is what "deliverer as a root source" looks like; it's the disease, not a config anchor.
- **Not a scheme, though authored like one.** A scheme is an identity recognizer: bound to one citation type, its match means "mint/dedup a child under the seeded platform root," and every `recognize_scheme` consumer treats a hit that way. A deliverer match means the opposite. Registering deliverers in the scheme registry would give every scheme consumer a second, inverted meaning of a match. What deliverers copy from schemes is the **authoring discipline**: pure-configuration records with no code, regexes permitted because authors are first-party (the same rule the scheme doc applies to shape fragments), malformed declarations failing at import, example-table tests per entry.
- **What it is: the fourth recognizer's host table, arriving early.** `recognize_url` is an ordered pipeline where each recognizer has a declared input — schemes have the spec registry, host matching has `CitationSourceRootDomain`. F1 is a planned fourth entry whose input is this table. Today only the guardrails consume it, because the access-URL outcome has no storage yet; when instance access URLs land, F1 becomes one more recognizer reading the same table, exactly the way `_recognize_by_host` reads root domains. It therefore reuses `hosts.py`'s label-boundary suffix matching verbatim, so deliverer hosts and root-domain hosts stay one vocabulary.
- **Module placement — and the storage vision.** An app-level leaf module beside `hosts`/`psl` in the citation app's import-linter stack (imports `hosts` only), so `models.py` can consume it for the `clean()` guard. It does not live inside the `citation_types` plugin package: it is core-owned configuration, not a third-party extension surface. **In-repo is the near-term state, not the end state**: like schemes, deliverers will be authored in a product UI and stored in the DB, and the two move together (the stored-configuration direction in [CitationPluginSystem.md](CitationPluginSystem.md)). Until then, adding a deliverer requires a deploy — an **accepted near-term cost** given a continuous-deploy cadence and a table expected to change rarely after the prod-clone calibration, not an architectural principle: code-shipped entries are a floor (the guard must hold on an empty DB), never an argument against stored rows on top. The spec's fields already split along the storage seam: `hosts`/`delivers`/`works_phrase` are inert data ready to become rows (the entire entry for most platforms), while the regex shapes (`isbn_path_patterns`, `kind_path_patterns`) are the same trust-gated residue the scheme plan names — the last part to open to non-repo authoring. If post-launch gardening surfaces new deliverer hosts at a recurring rate before the stored-config move happens, that's the signal to pull a simple stored tier (host + label + kind, admin-edited, unioned with the code table) forward ahead of the rest.

### Considered and rejected: one recognizer registry for schemes and deliverers

Poked at deliberately before implementation, because mechanically Amazon smells like a scheme: both are host-keyed, pattern-bearing, identifier-extracting configuration — Amazon's `/dp/{isbn10}` is a `UrlShape` with an `{id}` slot in all but name, and Zotero (the domain prior art) genuinely does unify them: its Amazon translator emits a book item through the same pipeline as its YouTube translator. The F4 extraction path is translator-like, and that concession is real.

Why the tables stay separate anyway:

- **Zotero can unify because it has one verb** — always "emit metadata into your library." Our outcome forks on a question Zotero never faces: does the platform own the work's identity in the shared catalog? A YouTube ID names a work whose home _is_ the platform (mint an identity child, store the identifier, build canonical/deep links); an ISBN names a work whose identity is independent of the host that delivered it (no Amazon-flavored row may ever exist).
- **The required/forbidden test.** A scheme's required core (`canonical_url_template`, `root_citation_source_info`, the seeded root, the `identifier_key` CHECK binding) is precisely the deliverer's forbidden set. Two record types sharing only `{label, hosts, patterns}` whose required cores are complements share a vocabulary, not a nature; a unified spec class is half-`None` in every instance, with the structural rules demoted to runtime validation.
- **Anchoring inversion.** Schemes match by _shape_ for precision (a YouTube homepage URL is deliberately not a scheme match — it falls to the root's host recognition); deliverers match by _host_ for recall (the default-deny must catch shapeless URLs too).
- **Disjoint consumers.** Outside the classifier, no consumer wants both: minting, deep links, the patch parser and upserts consume schemes only; messages and the `clean()` guard consume deliverers only. A merged registry would force kind-awareness into the scheme conformance harness, the JSON round-trip proof, the constraint derivation and the third-party authoring surface — every check forking on "is this a minting recognizer?" — to benefit exactly one join point.

Where unification **does** live, deliberately: (1) the **classification outcome** — `classify_url`'s sum type is the one system in which YouTube and Amazon are the same kind of thing, a URL verdict; and (2) the **matching vocabulary** — `hosts.py` suffix matching today, and the shape grammar tomorrow (see triggers).

**Convergence triggers**, so this stays a falsifiable checkpoint rather than a one-time judgment:

1. **A second global-identifier extractor ships** (page-metadata ISBN extraction and the Apple Podcasts lookup are both candidates; DOI-from-URL the obvious third) → factor extraction into a **translator layer** — Zotero's architecture arriving where it belongs: per-platform extractors whose contract is "URL, plus optionally page metadata → identifier-in-a-namespace + draft metadata," consumed by the classifier. Schemes = translation + platform-identity policy; deliverers = optional translation + never-identity policy. The input contract is deliberately **transport-agnostic**: whether page metadata came from a server fetch or a future privileged client (see browser-side capture below) is a transport detail.
2. **Post-F1, a scheme match records an access URL** (the re-hosted-work case VideoCitations.md predicts: a YouTube URL pasted against a movie) → scheme recognition producing a deliverer-flavored outcome is the moment to revisit whether the registries merge under the classifier.
3. **A fourth host-keyed table appears** (after root domains, scheme root info, deliverer hosts) → consolidate host policy generally rather than adding another parallel table.

### Considered and rejected (for now): browser-side capture

Zotero does its extraction in the user's browser; worth recording why we don't follow, and what keeps the option open. The technical anchor: **Zotero is an extension because of CORS, not by preference** — a web app cannot fetch a cross-origin page and read its HTML, so page-content capture requires a privileged context (extension content script, bookmarklet, or server fetch). "More capture in the browser" is therefore not a dial inside the SPA; it is a second product. What that product would buy is exactly one superpower: reading the page the user already has — their session, their cookies, a real browser — which defeats bot-blocking, paywalls and login gates completely. Rejected for now because:

- **The workflow inversion.** Zotero's premise is collect-now-cite-later into a personal library that exists independent of any document. Flipcommons has no library: evidence attaches to a claim at the moment of editing it, so a browser capture has nowhere to land without first building a "source inbox" staging surface — an F5-adjacent product decision, not an implementation detail. The extension is downstream of that decision, not upstream of it.
- **The gap is thin.** The pages pinball evidence lives on (Pinside, manufacturer sites, IPDB) scrape fine server-side or are schemes; the bot-blocked class is mostly the deliverers, where the guardrail means we don't want the page — we want the work, and the URL-embedded ISBN handles the highest-volume case with no fetch at all.
- **Disproportionate carry**: three browser stores, review cycles, a host-permissions trust ask, a second release cadence — sustained by Zotero through two decades of community translator maintenance we don't have.

What we do instead: the translator layer's **transport-agnostic input contract** (trigger 1 above) keeps a future bookmarklet or extension additive — a privileged client simply POSTs `{url, page_meta}` where the server fetch now supplies it; **extract failures are instrumented by host** (rehearsal step 6, then production telemetry) so a connector gets funded by evidence of real paste pain rather than architecture appetite; and the zero-privilege ergonomics get stolen now — ISBN-anywhere-in-paste (design details below), with a PWA share-target (mobile "share to Flipcommons," URL-only) as the later no-extension option.

### Prior art

The recognizer pipeline and this extension of it follow well-trodden shapes, which is worth recording because it means the design's instincts can be checked against systems that already work:

- **Chain of Responsibility / ordered choice**: ordered handlers, each answers or abstains, first answer wins; ordering is load-bearing (PEG-style prioritized choice). The host matcher is longest-suffix match, the DNS-shaped mirror of longest-prefix routing.
- **Firewall/routing rule tables** are the precedent for the deliverer entry specifically: a first-match rule whose action is REJECT rather than ACCEPT — same table discipline, different verb.
- **Zotero's translator architecture** (and Wikipedia's Citoid on top of it) is the domain prior art: an ordered set of per-site URL recognizers, each able to abstain, strong identifiers (DOI/ISBN) tried before scraping, a generic metadata scraper as the catch-all. **Wikidata** models the scheme half as data: URL match pattern (P8966) extracts an external ID from a pasted URL, formatter URL (P1630) rebuilds the canonical link — precisely the `url_shapes` + `canonical_url_template` pair.
- The recognizer ordering (identifier, then known item, then container attribution) is bibliographic practice — strongest evidence first — consistent with the FRBR framing in [CitationInstanceUrls.md](CitationInstanceUrls.md).

The prior art splits into **two families**, and knowing which one we are settles arguments. **Capture tools** (Zotero, Citoid) are single-user: items land in a personal library, so identity has no stakes and duplicates are a pane and a merge button. **Collaborative catalogs** (Wikidata, MusicBrainz, Discogs) share identity across contributors. On the deliverer question the catalog family is unanimous and matches this plan: MusicBrainz stores ASINs and Amazon links as **typed URL relationships on the release** ("purchase for download," "streaming page") — a store URL is never an entity, always an attribute of the work it delivers; Discogs keeps the marketplace outside the catalog entirely; Wikidata keeps store links out of Item-hood. That lineage is the direct precedent for what F1's access URLs become. Flipcommons is structurally a collaborative catalog; its **paste flow** is the one Zotero-shaped part (a capture pipeline), which is where Zotero's ideas transplant — the translator layer (trigger 1 above) and the page-metadata fallback (design details below). Also validating: both families converged on merge tooling (Zotero's duplicates pane, MusicBrainz's merge queues), so F6 is a law of citation systems, not cleanup debt from this design.

## Design spine: recognition becomes a classification

The pre-F2 architecture has one structural weakness, and it is the exact bug class this plan fixes: the recognizer pipeline can only say one kind of thing ("here is identity"), so every non-identity verdict lives as a **pre-check scattered across surfaces** — scheme-record rejection is a helper each endpoint must remember to call, and a naive F2 would add deliverer checks in three more places. `cite-url` mints Amazon roots today _because_ nothing forces it to consult a check that lives outside the pipeline.

F2 therefore introduces a **classification function** over pasted URLs whose result is a sum type, and every interactive surface switches on it exhaustively (no default arm), so a surface _cannot_ skip a verb:

```text
classify_url(url) →
    SchemeRecord(key, identifier)   cite via scheme:identifier (records/), never as a web page
    Identified(child)               an existing child covers this URL — reuse it
    SiteOf(root)                    a known site's page — mint a web child under the root
    Deliverer(spec, embedded_isbn)  a deliverer copy — teach / auto-classify; never web-create
    Unrecognized                    no verdict — the web-create funnel (new site) applies
```

The first three variants are re-namings of what `recognize_url` + the scheme pre-check already compute (the `Recognition` dataclass encodes them today as optional-field combinations); `Deliverer` is the new verb; `Unrecognized` is the explicit fallthrough. Deliverer classification runs **before** identity recognition — see ordering below. F1 later upgrades the `Deliverer` arm's handling (record access URL) without touching the classification itself; a future archive-peel is a preprocessing step in front of the classifier, per [CitationInstanceUrls.md](CitationInstanceUrls.md)'s pipeline sketch.

Scope honesty: the classifier fronts the **interactive** surfaces (`search`, `extract`, `cite-url`, `pages/`) in this slice. The patch path (`get_or_create_web_source`) is already safe by construction and converges on the classifier later rather than growing this PR.

## Near-term product spec (F2 + F4 + movie create)

### What pasting a deliverer URL does

Every scenario below starts the same way: the user pastes a URL into the cite picker's search stage and activates "Use this URL →" (or the search-as-you-type equivalent). Today all of them dead-end in the web-create flow with a fabricated "Amazon page" identity; with this work:

| Paste                                                                                              | Outcome                                                                                                                                                                                                                                            |
| -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Amazon book page (`/dp/<ISBN-10>`, any Amazon TLD)                                                 | The ASIN **is** the ISBN-10 → Open Library lookup → the **book form, prefilled** (title, author, publisher, year, ISBN). If a source with that ISBN already exists, it is offered for one-click citing — same as pasting the bare ISBN.            |
| Barnes & Noble book page (`?ean=<ISBN-13>`)                                                        | Same as Amazon books, via the declared query param.                                                                                                                                                                                                |
| Amazon non-book page (a `B0…` ASIN, a category page)                                               | **Teaching notice**: "Amazon delivers copies of works — cite the work itself (the book, movie or other work), not the Amazon page." CTA opens the authored-work form (type picker shown).                                                          |
| Amazon Prime Video page (`/gp/video/…` on the retail host)                                         | **Teaching notice** with video wording, video preselected — the declared per-path work-kind hint on the mixed storefront.                                                                                                                          |
| Streaming page (Netflix, HBO Max, Disney+, Hulu, Prime Video, Apple TV, Paramount+, Peacock, Tubi) | **Teaching notice** with video wording ("cite the movie or video itself"). CTA opens the authored-work form with **video** preselected — creating a movie, the parentless-citable video work F3 enabled.                                           |
| Book retailer with no embedded ISBN in the URL (AbeBooks listing page, Apple Books, Google Books)  | **Teaching notice** with book wording; CTA opens the form with **book** preselected.                                                                                                                                                               |
| Audiobook page (Audible `/pd/<slug>/<B0…>`)                                                        | **Teaching notice** with audiobook wording ("Audible delivers audiobook editions of books — cite the book itself"); CTA opens the form with **book** preselected. A timestamp is a legal freeform book locator, so "where I heard it" still works. |
| Any non-deliverer URL                                                                              | Unchanged: recognition, web-create, scheme rejection all behave as today.                                                                                                                                                                          |

The teaching notice replaces the advance into web-create — the user can never reach the "Create site" panel for a deliverer URL. It renders where extraction errors render today, with the CTA as the only forward action; searching for an existing source stays available as always. The handoff seed carries the pasted URL through flow state even though nothing stores it yet — the F7 hedge, so threading the access URL later is plumbing rather than a flow redesign.

### The API is guarded too, not just the UI

The SPA guardrail is UX; the backend holds the invariant (the same split as auth gates). `cite-url` and `pages/` switch on the classification and 422 the `Deliverer` arm with the teaching message, and `CitationSourceRootDomain.clean()` rejects a deliverer host outright — so neither a raw API caller, an admin-inline edit, nor a future patch can register `amazon.com` as a recognition domain.

### Interactive movie create

The video-deliverer handoff needs somewhere to land: the authored-work form today offers only book and magazine, so there is no interactive way to create a movie. The form gains a **video** type chip (plus a Year field for video — a movie's main disambiguator across remakes), and `POST /citation-sources/` accepts `source_type: video` for **roots only**: a movie is a parentless work, platform videos mint via `records/` from their URLs, and an authored video _child_ has no meaning (it would sidestep the scheme path exactly the way a hand-typed web child would).

### Audiobooks are book editions, not a new type

Decided while adding Audible to the table: an audiobook is a **manifestation of the book** (the FRBR ladder [CitationInstanceUrls.md](CitationInstanceUrls.md) already leans on), not a new work and not a new citation type. Consequences:

- **Audible is a book deliverer.** Its handoff lands on the book form; the work cited is the book. Audiobook ASINs are `B0…` (not ISBNs — audiobooks carry separate ISBNs that Audible URLs don't expose), so there is no extraction, only the notice.
- **The precision already exists for contributors who want it.** An "audiobook edition" is representable today as an authored child of the book — the same edition shape print editions use — and a timestamp is already a legal locator (the freeform book locator's placeholder literally offers "timestamp…"). Nothing new to build; per-copy timing drift gets anchored by the instance's access URL when that lands, the same answer the movie case settled.
- **No `audiobook` citation type, and the deferred `audio` type stays deferred.** [VideoCitations.md](VideoCitations.md) already records that an audio type earns its slot only on podcast-shaped demand (the episodic show → episode seam plus an RSS/Apple/Spotify identifier story). An audiobook has none of that structure — it behaves exactly like a book with a timestamp-shaped location, which the freeform locator already permits.

## The deliverer survey

The initial table, with the actual rule per platform. **Verification status is flagged honestly**: URL shapes marked ⚠ are from knowledge, not live checks (web verification was unavailable when surveyed), and are confirmed cheaply during the prod-clone rehearsal by pasting real pages; every rule is written to degrade safely if a shape is wrong (a missed extraction falls back to the notice, never to web-create).

| Deliverer      | Hosts                                                                                                                                                                                                                                                 | URL shapes that matter                                                                                                                                                                         | Rule                                                                                                                                                                                                                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Amazon         | `amazon.com` + country TLDs (`.co.uk`, `.de`, `.fr`, `.it`, `.es`, `.ca`, `.co.jp`, `.in`, `.com.au`, `.com.br`, `.com.mx`, `.nl`, `.se`, `.pl`, `.com.tr`, `.ae`, `.sa`, `.sg`, `.eg`, `.cn`); short links `a.co`, `amzn.to`, `amzn.eu`, `amzn.asia` | `/dp/<ASIN>`, `/<slug>/dp/<ASIN>`, `/gp/product/<ASIN>`; ⚠ mobile `/gp/aw/d/<ASIN>`, legacy `/exec/obidos/ASIN/<ASIN>`, locale prefix `/-/en/`; `/gp/video/…` (Prime Video on the retail host) | ISBN-10-shaped ASIN (shape + checksum) → **book auto-classify**. Kindle/e-book ASINs are `B0…` and never match → notice. `/gp/video/` → video-kind hint. Short-link hosts are opaque (no extraction) → mixed notice. Else mixed notice.                                                |
| Barnes & Noble | `barnesandnoble.com`, `bn.com`                                                                                                                                                                                                                        | ⚠ `/w/<title-slug>/<work-id>?ean=<ISBN-13>` — `ean` common in shared links, not guaranteed                                                                                                     | `ean` param (checksum) → **book auto-classify**; else book notice.                                                                                                                                                                                                                     |
| AbeBooks       | `abebooks.com`, `.co.uk`, `.de`, `.fr`, `.it`                                                                                                                                                                                                         | ⚠ `?isbn=<isbn>` (search/listing params); ⚠ leading-ISBN paths `/9780…/<slug>/plp`                                                                                                             | `isbn` param or leading-ISBN path (checksum) → **book auto-classify**; else book notice.                                                                                                                                                                                               |
| Audible        | `audible.com`, `.ca`, `.co.uk`, `.com.au`, `.de`, `.fr`, `.it`, `.es`, `.in`, `.co.jp`                                                                                                                                                                | ⚠ `/pd/<slug>/<ASIN>` — audiobook ASINs are `B0…`, never ISBNs                                                                                                                                 | No extraction possible → book notice with the audiobook `works_phrase` ("audiobook editions of books — cite the book itself").                                                                                                                                                         |
| Netflix        | `netflix.com`                                                                                                                                                                                                                                         | `/title/<numeric-id>`, `/watch/<id>`, optional region prefix                                                                                                                                   | IDs opaque (no public resolution) → video notice, always.                                                                                                                                                                                                                              |
| HBO Max        | `hbomax.com`, `max.com` (and `play.` subdomains via suffix match)                                                                                                                                                                                     | ⚠ `/movie/<uuid>`, `/show/<uuid>` — 2025 re-rebrand back to HBO Max; keep both domains                                                                                                         | IDs opaque → video notice.                                                                                                                                                                                                                                                             |
| Disney+        | `disneyplus.com`                                                                                                                                                                                                                                      | ⚠ `/browse/entity-<uuid>` (current), `/movies/<slug>/<id>` (legacy), `/play/<uuid>`                                                                                                            | IDs opaque → video notice.                                                                                                                                                                                                                                                             |
| Hulu           | `hulu.com`                                                                                                                                                                                                                                            | `/movie/<slug>-<uuid>`, `/series/<slug>-<uuid>`, `/watch/<uuid>`                                                                                                                               | IDs opaque → video notice.                                                                                                                                                                                                                                                             |
| Prime Video    | `primevideo.com` (international host; retail-host shapes live under Amazon)                                                                                                                                                                           | `/detail/<id>`, region-prefixed variants                                                                                                                                                       | IDs opaque → video notice.                                                                                                                                                                                                                                                             |
| Apple          | `tv.apple.com` (video), `books.apple.com` (book), `itunes.apple.com` (mixed)                                                                                                                                                                          | ⚠ `/<region>/movie/<slug>/umc.cmc.<id>`; `/<region>/book/<slug>/id<store-id>` and `/<region>/audiobook/<slug>/id<store-id>` (store ids ≠ ISBN)                                                 | Per-host kind → video / book / mixed notice; audiobook paths are just books. No extraction (Apple store ids aren't ISBNs).                                                                                                                                                             |
| Google         | `play.google.com` (mixed), `books.google.com` (book)                                                                                                                                                                                                  | `/store/books/details?id=…` vs `/store/movies/details?id=…` vs `/store/audiobooks/details?id=…` (path discriminates kind); `books.google.com/books?id=…`                                       | Play: per-path kind hint (books/audiobooks → book, movies → video), else mixed notice. Books: book notice; ids opaque. **Known miss**: new-style `google.com/books/edition/<slug>/<id>` lives on `google.com`, which cannot be host-blocked — accepted; rare; F5 gardening catches it. |

Path-level rules obey one invariant: **a path shape tunes the message wording and the create form's preselected type; it never changes the outcome.** Outcomes come only from the two declared extraction families (embedded-ISBN → auto-classify) and the host itself (→ notice). A general per-path treatment router is deliberately out of scope: an ISBN is the only identifier resolvable into a work draft today (streaming IDs are opaque without per-platform APIs), and the real path-shape machinery is F1.

**Known false-positive class, accepted**: suffix matching on `amazon.com` also swallows non-store subdomains (`aws.amazon.com` documentation is a legitimately citable web page). Accepted for a pinball knowledge base; an `except_hosts` carve-out field is the designed escape hatch if it ever bites.

**Deliberate exclusions**, recorded as decisions:

- **eBay** — a listing's photos can be primary evidence for collecting claims; a listing is sometimes genuinely the cited page.
- **archive.org** — also a legitimate page host for scans today; Wayback URLs get the _peeling_ treatment planned in [CitationInstanceUrls.md](CitationInstanceUrls.md), not a deliverer block.
- **IMDb** — not a deliverer at all: a reference catalog _about_ films (the IPDB shape). Citing IMDb pages as web pages is legitimate; a future movie scheme is its plausible end state.
- **YouTube et al.** — already schemes; the re-hosted-work question (a documentary uploaded to YouTube) is the separate hole recorded in [VideoCitations.md](VideoCitations.md), resolved by access URLs, not by this table.
- **Spotify** — excluded for now, for two reasons that fall out of our own rules. Blocking `open.spotify.com` would strand **podcast** evidence (pinball podcasts are plausible citations) with no landing type — no podcast/audio type exists yet, so an episode's least-bad home remains a web child, exactly the status videos had on unschemed platforms pre-video-type. And scoping deliverer-ness to just its `/audiobook/…` paths would make a path pattern change the **outcome**, violating the tunes-message-never-outcome invariant. Both reasons dissolve the moment a podcast type exists — the [podcast stress test](#stress-test-how-podcasts-land) records the resolved entry, and it is a deliverer entry, **not** a scheme.

## Concrete per-deliverer configuration

The exact declarations, written as data so review argues about facts, not code. Field semantics and interpretation rules first:

- **Matching**: a URL is classified `Deliverer` when its normalized host has any declared host as a label-boundary suffix. Within a matched entry, evaluation order is: (1) ISBN extraction — each `isbn_query_params` value and each `isbn_path_patterns` match is stripped of hyphens/spaces, shape-checked (10 or 13), checksum-validated, first valid wins → auto-classify; (2) `kind_path_patterns`, first match → notice with that work kind preselected; (3) the entry's `delivers` default → notice. Path patterns run `re.search` against `urlparse(url).path` only; query params via `parse_qs`. Every failure falls through to the next step — a wrong shape degrades to the notice, never to web-create.
- **Messages** derive from `delivers` (or the per-entry `works_phrase` override when the default noun is wrong):
  - book → "{label} delivers copies of books — cite the book itself, not the {label} page."
  - video → "{label} delivers copies of movies and shows — cite the movie or video itself, not the {label} page."
  - mixed → "{label} delivers copies of works — cite the work itself (the book, movie or other work), not the {label} page."

```yaml
- label: Amazon
  hosts:
    [
      amazon.com,
      amazon.ca,
      amazon.com.mx,
      amazon.com.br,
      amazon.co.uk,
      amazon.de,
      amazon.fr,
      amazon.it,
      amazon.es,
      amazon.nl,
      amazon.se,
      amazon.pl,
      amazon.com.tr,
      amazon.ae,
      amazon.sa,
      amazon.eg,
      amazon.in,
      amazon.sg,
      amazon.co.jp,
      amazon.cn,
      amazon.com.au,
      a.co,
      amzn.to,
      amzn.eu,
      amzn.asia,
    ]
  delivers: mixed
  isbn_path_patterns:
    ['/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN)/(?P<isbn>\d{9}[\dXx])(?=/|$)']
  kind_path_patterns: [["/gp/video/", video]]
  # Short-link hosts (a.co, amzn.to, …) are opaque redirects: no path to extract
  # from, so they always land on the mixed notice. Kindle ASINs are B0… and
  # never match the ISBN-10 shape. aws.amazon.com is a known accepted FP.

- label: Audible
  hosts:
    [
      audible.com,
      audible.ca,
      audible.co.uk,
      audible.com.au,
      audible.de,
      audible.fr,
      audible.it,
      audible.es,
      audible.in,
      audible.co.jp,
    ]
  delivers: book
  works_phrase: audiobook editions of books
  # /pd/<slug>/<ASIN> ASINs are B0…, never ISBNs → notice only.

- label: Barnes & Noble
  hosts: [barnesandnoble.com, bn.com]
  delivers: book
  isbn_query_params: [ean]

- label: AbeBooks
  hosts: [abebooks.com, abebooks.co.uk, abebooks.de, abebooks.fr, abebooks.it]
  delivers: book
  isbn_query_params: [isbn]
  isbn_path_patterns: ['^/(?P<isbn>97[89]\d{10})(?=/|$)']

- label: Apple TV
  hosts: [tv.apple.com]
  delivers: video

- label: Apple Books
  hosts: [books.apple.com]
  delivers: book
  # /<region>/book/… and /<region>/audiobook/… are both books; store ids ≠ ISBN.

- label: iTunes
  hosts: [itunes.apple.com]
  delivers: mixed

- label: Prime Video
  hosts: [primevideo.com]
  delivers: video

- label: Netflix
  hosts: [netflix.com]
  delivers: video

- label: HBO Max
  hosts: [hbomax.com, max.com]
  delivers: video

- label: Disney+
  hosts: [disneyplus.com]
  delivers: video

- label: Hulu
  hosts: [hulu.com]
  delivers: video

- label: Paramount+
  hosts: [paramountplus.com]
  delivers: video

- label: Peacock
  hosts: [peacocktv.com]
  delivers: video

- label: Tubi
  hosts: [tubitv.com]
  delivers: video

- label: Google Play
  hosts: [play.google.com]
  delivers: mixed
  kind_path_patterns:
    [
      ["^/store/books/", book],
      ["^/store/audiobooks/", book],
      ["^/store/movies/", video],
    ]

- label: Google Books
  hosts: [books.google.com]
  delivers: book
```

The YAML is the spec, not the storage: entries ship as in-repo declarations (the `DELIVERERS` tuple), and this block is kept in sync by being the review artifact when the table grows. `works_phrase` exists because one label (Audible) needs a truthful noun the `delivers` kind can't derive; it changes wording only.

## Design details

- **The spec record**: `label`, `hosts` (normalized, label-boundary suffix matched, enumerated — no wildcards), `delivers` (**typed open over interactively-creatable citation-type keys**, or mixed — not a closed `book | video` pair; the [podcast stress test](#stress-test-how-podcasts-land) is why), `isbn_path_patterns` / `isbn_query_params` (where an ISBN rides when it does), `kind_path_patterns` (the mixed-storefront work-kind hints, same open vocabulary), `works_phrase` (optional message-noun override; wording only). Declarations say **where to look**; shape + checksum validation is interpretation-side, so a coincidental ten-character token can't trigger a bogus lookup. Import-time validation mirrors scheme registration: un-normalized/non-DNS hosts or a host declared twice fails at import.
- **Ordering is load-bearing**: deliverer classification runs **before** identity recognition on every interactive surface. Prod data may already contain an interactively-minted `amazon.com` root with a recognition domain; if the check ran after `recognize_url`, a domain match would short-circuit past the guardrail and mint another child under the misclassified root. The `search` endpoint likewise suppresses recognition for deliverer URLs so the UI never shows a "Cite a page under Amazon.com" row sourced from legacy data.
- **Existing misclassified rows stay.** Sources and citations already pointing at deliverer children remain readable and re-citable through their existing child links; repairing them is F5/F6 gardening. The guardrail's job is to stop the bleeding, not rewrite history.
- **The extract flow (F4)**: `Deliverer` arm → declared ISBN extraction from the URL → **page-metadata fallback** when the URL embeds nothing: fetch the page through the existing `safe_fetch` + head-parser machinery and look for schema.org Book / `og:book:isbn` markup — the Zotero lesson that the page often carries the identifier the URL doesn't. Expected to work for B&N and Google Books; expected to be bot-blocked by Amazon (whose server fetches 503 — Zotero escapes that only by running in the user's browser); a blocked or empty fetch degrades to the notice, same ladder. Any ISBN found → `extract_isbn` (existing Open Library path, including its existing-source match check). A lookup yielding neither match nor draft falls back to the notice, never to a raw error. The extract response gains a structured `deliverer` field (`label`, suggested work kind) — never an error string, because the frontend branches on it for wording and CTA preselection.
- **ISBN-anywhere-in-paste**: `classify_input` currently demands the whole paste be an ISBN or a URL; loosen it to find an ISBN anywhere in pasted text ("Pinball Compendium 978-0764325847 — amazon.com/…"). Zotero's add-by-identifier wand accepts messy input, and so should the capture edge — a few lines in the same classification function. (Precedence stays ISBN-first, matching the existing rule.)
- **Frontend**: the search stage routes extraction drafts by `source_type` instead of assuming URL ⇒ web (removing a hidden assumption rather than adding a special case), renders the notice in the extraction-error slot with a single CTA into the create flow, and the `name` create seed gains an optional preselected source type plus the pasted URL (the F7 hedge). The preselect mechanism takes **any** type key rather than special-casing book/video, for the same open-vocabulary reason as `delivers`. The create stage adds the `video` chip and a Year field for video; web stays URL-only.
- **`CitationSourceRootDomain.clean()`** rejects deliverer hosts on every validated write path (API, admin inline, patch declare). App-level rather than a CHECK constraint because suffix-matching a changing table isn't portable DDL, and the table should grow without migrations. No DB migration anywhere in this slice.

## Stress test: how podcasts land

A worked example, **not scheduled work**: the next plausible citation type pushed through this design on paper, to verify it absorbs the type without rework and to pin the F2 decisions that only become visible under a third work kind. The podcast type itself stays demand-gated per [VideoCitations.md](VideoCitations.md)'s audio decision; if pinball-podcast demand is judged real, it is a dedicated follow-up PR after this slice (migration + timestamp refactor + flippatch ordering + frontend type registry), never folded in.

**The type is absorbed almost entirely by existing machinery.** `SourceType` gains `podcast` (the CHECK constraints derive from the enum, so this is a `makemigrations`, not a hand-edit). The spec record is an unremarkable new trait combination: `schemeless_parentless_abstract=True` (a show is a container — the magazine shape), `flat_hierarchy=True` (show → episode, one level), `child_skips_locator=False` (an episode _wants_ a timestamp — the whole point), locator = the timestamp contract. The one real refactor is the pre-recorded one: the timestamp grammar moves from `video.py` to a shared `citation_types/timestamps.py` and both types declare the same `LocatorContract` — the payoff of putting locator semantics on the type axis. Shows and episodes are created through the authored-children flow book editions already use; episodes get the prompted locator stage video children already get.

**There is no podcast scheme — and that's the finding, not a gap.** A YouTube video is (mostly) born-digital and single-homed, which is why video schemes work; re-hosted works are the recorded exception. For podcasts the exception is the rule: **every** episode is multi-homed (Spotify, Apple Podcasts, Overcast, the RSS enclosure, the show's own site), so a platform scheme would systematically enshrine access as identity and fragment every episode per platform — the Amazon problem as a design guarantee. Identity is the show root + episode child; the RSS `<guid>` is the canonical identifier story if episode-level dedup ever needs one. Podcasts are the first type **born into the deliverer model**: platform URLs never mint identity children, and the "example hosts" enter the system as deliverer entries:

```yaml
- label: Spotify
  hosts: [open.spotify.com, spotify.link]
  delivers: mixed
  kind_path_patterns:
    [["^/episode/", podcast], ["^/show/", podcast], ["^/audiobook/", book]]
  # Default stays mixed: /track|/album|/playlist are music, which has no citable
  # type at all — the generic "cite the work itself" is the honest fallback.
  # spotify.link short links are opaque redirects, notice only.

- label: Apple Podcasts
  hosts: [podcasts.apple.com]
  delivers: podcast
  # /<region>/podcast/<slug>/id<show-id>?i=<episode-id>. Show ids are publicly
  # resolvable via the iTunes lookup API (show metadata + RSS feed URL, no key)
  # — the podcast analog of Open Library, i.e. a future F4-style auto-classify
  # that could prefill the show (and with the feed, the episode). No other
  # streaming entry in the table has a resolvable identifier.
```

**What the stress test changes in F2 now** (adopted into the design above, and worth doing regardless of whether podcasts ever ship):

1. `delivers` and the `kind_path_patterns` kind slot are typed **open over citation-type keys** (plus mixed), not a closed `book | video` literal — in the spec record and in the wire schema's `deliverer` field, so the vocabulary growing is additive rather than a schema break.
2. The create-form preselect handoff takes any type key.
3. The Spotify exclusion is confirmed as temporary, with its resolved shape recorded above.

**What it doesn't change**: the classification verbs, the table mechanics, the `clean()` guard, the invariant (Spotify's kind paths tune wording/preselect only; its outcome is the notice regardless of path), and the message templating (a podcast template — "delivers copies of podcast episodes — cite the episode itself" — arrives with the type).

## Rollout

One PR, multiple commits (classification + table + backend guardrails; ISBN auto-classify; create-form video extension; frontend teaching flow).

**Prod-clone rehearsal before shipping** — validation and data-gathering in one pass, mechanized by a small read-only management command:

1. **Inventory the existing damage**: `CitationSourceRootDomain` rows on deliverer hosts; web children under them; `CitationInstance` rows citing those children. PROTECT means none of it deletes — this sizes the F6 merge backlog and tells us whether "existing rows stay" is a footnote or a visible wart.
2. **Derive the table from data**: dump distinct hosts of existing web-child reference links and eyeball for deliverer-shaped ones — the survey's guesses replaced by the platforms contributors actually paste.
3. **Check for false positives**: any existing child on a to-be-blocked host that is a _legitimate_ page cite (the `aws.amazon.com` class) argues for the `except_hosts` carve-out before launch rather than after.
4. **Verify the ordering claim**: with a legacy `amazon.com` root present, paste an Amazon URL and confirm the notice — not a child minted under the legacy root. This is the one behavior that only manifests against prod-shaped data.
5. **Confirm the ⚠-flagged URL shapes** in the survey by pasting live pages per platform.
6. **Measure server-fetch viability per deliverer host** for the page-metadata fallback (which hosts 503/bot-block a server fetch), and instrument extract failure modes by host — the baseline for the browser-capture telemetry trigger.

The inventory's `created_at` distribution also settles a sequencing question with data: if deliverer-host children show steady interactive accretion, the guardrail-first ordering below is confirmed; if there are near-zero, urgency was assumption.

The table will be wrong in both directions at first (missing platforms, arguable inclusions); growing it is one declaration per platform, and `clean()`-level enforcement means no migration churn as it grows.

## Sequencing

**F2/F4** (+ the movie-create form extension) ship now, **before** instance access URLs, for three reasons considered and settled: access URLs stop no damage by themselves (the web-create path would still mint Amazon sites without this table), the size asymmetry is large (this slice is additive with no migrations; access URLs v1 is a structural project — the normalized identity-URL table, cross-repo patch-grammar ordering, Wayback peeling), and there is no rework tax (F1 upgrades the `Deliverer` arm's handling; the table, the classification, and the 422 backstops all remain as-is). The F7 hedge (pasted URL carried through the handoff seed) keeps the later upgrade to plumbing.

The structural pieces (F1/F5/F6/F7) sequence after instance access URLs. F1 consumes the F2 deliverer table and classification when it arrives.
