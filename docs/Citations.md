# Citations

The citation system records the external **evidence** that supports a claim in the catalog. It lets readers and contributors answer two questions quickly: what external evidence backs this statement, and how can I inspect that evidence myself.

## Citations vs provenance

Citations are not provenance. The two systems answer different questions:

- **Provenance** tracks, via Claims, _who asserted_ a piece of data into the project — a user or an ingest run. See [Provenance.md](Provenance.md).
- **Citations** track _what external evidence_ supports a Claim.

Consequently, citation sources are **not claims-controlled**. Unlike user-inputted catalog fields, citation sources are edited directly through the API and admin, not through the claims workflow. (The link _from_ a claim to its evidence is provenance's concern — see below.)

## Data model

```text
Scalar/edit claim ──── `ClaimCitationInstance` join ────┐   (provenance app)
                                                        ▼
Markdown passage ──── `[[cite:…]]` marker ────▶ `CitationInstance`   (one use of a source, with a locator)
                                                        └── `CitationSource`    (the work or evidence object)
                                                              └── `CitationSourceLink`(s)   (ways to inspect the source)
```

### CitationSource

A `CitationSource` is the shared work or evidence object — a book, a magazine, a web page, a database record. It is a **shared record**: when many pages cite the same book they should normally point at the same source, which is what makes deduplication and consistent presentation possible.

Sources may be **hierarchical** via a self-referential parent, when the domain needs it: work → edition, publication → issue → article, web root → child page. The hierarchy represents source _identity_, not locator position. Children do not inherit fields from their parent — prefill in the UI is fine, inheritance in the data is not.

A source carries a pragmatic `source_type` (book / magazine / web). Its job is to drive product behavior — search, edit fields, locator prompts, rendering — not to be a bibliography ontology, so the taxonomy stays small and grows only when a new type needs distinct behavior.

Some sources are **abstract** — a container rather than citable evidence: any source with children, or a parentless web or magazine root (a site, a publication). Contributors cite a concrete child instead — a page under a web root, an edition under a book; a parentless book with no children is itself the work, so it stays citable. `is_abstract` is a computed display hint (on the search API) that steers the authoring UI toward children. For web roots it is also structural: the cite paths resolve a URL to a child under the matched root (described below), so the abstract root is never the cited record.

For source families with structured identifiers, two paired fields express the scheme:

- `identifier_key` — the scheme, set on a **root** source only (e.g. an IPDB or OPDB root). A root is a scheme-holder.
- `identifier` — the structured value within that scheme, set on a **child** only (e.g. IPDB machine `4443`). A child is a value-holder.

A source is a scheme-holder _or_ a value-holder, never both. Children with identifiers are unique within their parent. A web child sets `skip_locator` — its URL _is_ the locator, so the authoring UI skips the locator step.

### CitationInstance

A `CitationInstance` is a single use of a source in a specific place, usually with a locator (page, timestamp, section, fragment). It is **shared evidence** with no single owning claim, reached through two channels: a scalar/edit citation is attached to claims through the `ClaimCitationInstance` join (one instance per distinct citation in a save, fanned out to every claim the save wrote), while an inline footnote is reached only by its `[[cite:…]]` marker and carries no join rows. Instances are **immutable**: changing a locator produces a new citation instance plus an ordinary edit, not mutated history in place — that copy-on-write rule, not per-use duplication, is the invariant.

`CitationInstance` lives in the **citation app**, beside `CitationSource` — the citation app owns the whole evidence domain, the work and the uses drawn from it. The one thing that must know about both `Claim` and `CitationInstance` — the claim ↔ evidence edge — is the `ClaimCitationInstance` join, which lives in the **provenance app** beside `Claim` and imports citation downward.

The text uses **point citations**, not text ranges. An inline marker sits at a position and means "this source supports the nearby claim", usually the preceding sentence. Ranges look more precise but demand discipline contributors won't sustain and produce misleadingly precise markup.

The inline marker is a normal **public-id wikilink** keyed on the instance's durable, author-stable **`slug`**: authoring form `[[cite:<slug>]]`, storage form `[[cite:id:<pk>]]` (the same authoring↔storage split as `[[title:…]]` and the other link types).

### CitationSourceLink

A `CitationSourceLink` is a reader-facing access point — a canonical URL, an archive URL, an uploaded scan, a museum-hosted copy. Links are ways to _inspect_ a source, not separate sources. They are wholly owned by their source.

Each link carries a `link_type`. `homepage` marks a source's own root page and is the human-facing URL for a root — it is **display only**, not the recognition signal. Recognition keys off `CitationSourceRootDomain` (see below), an owned recognition host on the root, decoupled from the homepage link so editing the display URL never silently changes matching. Every type (`homepage`, `reference`, `archive`, …) is a plain access point with no recognition role.

### Recognition hosts — `CitationSourceRootDomain`

A root's recognition host(s) live in `CitationSourceRootDomain`: a normalized host (lowercased, all leading `www.` labels stripped) that is globally `unique` and resolves to the root that owns it. Recognition is **type-blind**: any root — not just a web root — may own a recognition host and the web children it mints, so a magazine or book root with its own site (e.g. a magazine root owning `pinball-magazine.com`) recognizes URLs and nests web pages exactly like a web root does. One root may own many hosts (a rebrand's old + new domain, a `.com` + `.co.uk`, an asset subdomain). It is an owned fact, set deliberately at root creation, through seed data, or by an admin — never inferred later from edited links and never via external HTTP. Every stored recognition host must be a DNS host and must not be a bare public suffix such as `com`, `co.uk`, or `github.io`; otherwise longest-suffix matching would over-match unrelated sites. Recognition matches a pasted URL's host to the root whose recognition host is the **longest label-boundary suffix** of it, so `s4.american-pinball.com` collapses to the `american-pinball.com` root while a deliberately-seeded `twip.kineticist.com` still wins over `kineticist.com` for its own subtree.

## Authoring model

Citation authoring stays cheap at the moment of editing — Wikipedia's verification loop without the bureaucracy. The `[[` autocomplete is the front door; contributors don't pick a separate citation mode first. The same input accepts search text or pasted evidence (a URL or ISBN).

Reuse is primary but never gating: **centralization assists citation reuse, it does not gate citation authoring.** Shared sources are the long-term model and duplicate detection matters, but perfect deduplication isn't a prerequisite for saving — cleanup and merging can happen later.

## Recognition and extraction

When a contributor pastes evidence, the system tries to reuse an existing source first and only then helps create a new one. There are two layers with different trust models and performance profiles. Both produce a draft or a pointer for the contributor to confirm — neither silently auto-creates from low-confidence input.

### Recognition — local, fast

Recognition maps input to **existing data** using local DB queries only, with no external HTTP. It is folded directly into the search endpoint so typeahead stays fast. `recognize_url` resolves in three steps of decreasing confidence:

1. **Extractor match** — the URL matches a known scheme; an `Extractor` extracts and validates the identifier, then looks up the root and existing child. High confidence: one-click child creation is appropriate.
2. **Full-URL child-link match** — the URL exactly matches a stored child link. High confidence: re-citation of a known page.
3. **Recognition-host match** — the hostname resolves to a root via its `CitationSourceRootDomain` (longest label-boundary suffix wins, so subdomains collapse to the owning root). Lower confidence: this suggests parent _reuse_ only, so the UI pre-selects the parent but still asks for child details.

The read path is deliberately PSL-free: it suffix-matches only against stored, validated recognition hosts. Public Suffix List logic is write-time only, where it guards stored hosts and rounds an unrecognized pasted URL to the registrable domain before creating a new root.

The schemes live in an extractor registry keyed by `identifier_key` (currently IPDB, OPDB and YouTube). Each `Extractor` knows how to pull an identifier from a URL, validate a bare identifier and build the canonical URL. YouTube accepts any of its URL shapes — `watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`, `/live/` — and collapses them to the canonical `watch?v=<id>`, so the same video cited through different shapes resolves to one child.

Two idempotent helpers, `get_or_create_external_source` (scheme + identifier) and `get_or_create_web_source` (raw URL), are the entry points ingestion uses to attach evidence. The web helper runs the same `recognize_url`, so a URL reuses an existing **child** or nests a new child — with a `reference` link, never `homepage` — under a domain-matched root; even a URL equal to a root's own homepage nests a child, never returning the abstract root. A URL whose domain matches no seeded root **raises** rather than minting a parentless source: a root web source is an abstract container, not directly-citable evidence, so the website root must exist first.

### Extraction — external, slow

Extraction fetches **new metadata from external services** and proposes a draft source for confirmation. Because it does external HTTP with variable latency and multiple failure modes, it is a **separate endpoint** from search, never folded into the search response — search must stay fast and must not degrade when an external service is down.

Implemented today:

- **ISBN → Open Library** — classify the input, look up locally, then cache, then the Open Library API; returns a draft (or an existing match the text search missed).
- **Generic URL → page metadata** — fetch the page and parse `<title>` / Open Graph tags into a sparse draft.

The result is always one of: a draft, an existing match, or a structured failure (`not_found`, `timeout`, `parse_error`, …). Extraction produces a **draft, not an auto-create** — external-service confidence is lower and editorial review has value. (This draft-first rule is specific to extraction; recognition resolving to validated local data can be one-click.)

### Interactive web create

Pasting a web URL always follows the same shape — **Create Site → Create Page** — with recognition collapsing the steps that are already settled:

- **Existing page** (the URL exactly matches a child): cited directly, no create steps.
- **Existing site, new page** (the domain matches a root): only the **page** step shows, headed "Cite a page under _X_".
- **New site**: both steps — **describe-site** then **page**.

The **describe-site** step has a Site name (prefilled from the scraped `og:site_name`, else the domain, so it always shows the name the new root will get; the backend also defaults a blank name to the domain) and an optional manual Site description. The **page** step has a Page name (prefilled from `og:title`) and the URL for confirmation (editable when the scrape failed). There is no Author or Year anywhere — a web citation is a site plus a page, not an authored dated work.

Nothing is written until the contributor commits: the finalize button calls `cite-url`, which in one transaction creates the site root (its `homepage` link and `CitationSourceRootDomain`) when new and a page child under it, then cites that child. Abandoning beforehand writes nothing. `cite-url` re-recognizes the URL server-side and re-derives the same buckets — no match rounds the pasted host to its registrable domain, creates the root and child there, and rejects IP literals, reserved TLDs such as `.test` / `.example`, and bare public suffixes; a domain match nests a new child under the existing root (ignoring the site fields — the root is never renamed from here); an exact child is reused; a scheme URL (IPDB/OPDB/…) is rejected in favor of its `scheme:identifier` form — so the server, not a trusted frontend `parentId`, decides where the child lands. The cited record is always the page child, never the abstract root.

This is the interactive counterpart to the ingestion helper `get_or_create_web_source` above: the helper raises on an unseeded domain, while `cite-url` is allowed to mint the root because the contributor describes it in the same flow.

### SSRF safety

Generic URL fetching goes through a guarded fetch that validates the target **by resolved IP, not by hostname**. It resolves DNS before connecting and checks that the resolved IP is globally routable, which closes the DNS-rebinding window and catches internal hosts (they resolve to private IPs) without a fragile hostname blocklist. Only `http`/`https` are allowed, redirects are re-validated each hop, and a wall-clock deadline bounds the whole chain. This applies to the generic URL fallback, not to hardcoded known-API endpoints like Open Library.

## Seeding

Heavily reused source families are pre-seeded so autocomplete is useful from the start and contributors don't recreate the same records. Seed data is grouped by kind (books, magazines, websites) and applied through an idempotent upsert that creates or updates sources and reconciles their links, so reseeding is safe. Seeded sources can declare additional recognition-only hosts for rebrands, alternate TLDs, asset hosts and publication subdomains. Declared hosts are verbatim facts: they are normalized and validated, but not rounded to their registrable domain. Pre-seeding is especially worthwhile for bounded pinball-specific corpora — major books, magazines, manuals and database sites.

## Reader experience

On read, inline citations render as superscript references and a page with any citations shows a references section. Each entry shows the source, the locator and any useful access links. Scalar-claim citations and inline citations surface as one coherent evidence list. Pages with no citations are allowed — citations improve trust and maintainability but are not a prerequisite for contribution.

## Authorization

All mutating citation routes — create, update, extract, link management — are gated by the `CITATION_EDIT` activity, and the extract endpoint is additionally throttled to bound external-service abuse. See [Authz.md](Authz.md) for how activity gates work.

## Not yet built

- DOI → publication metadata extraction (ISBN and generic URL are done).
- Richer generic-URL extraction beyond title / Open Graph tags.
