# Citations

The citation system records the external **evidence** that supports a claim in the catalog. It lets readers and contributors answer two questions quickly: what external evidence backs this statement, and how can I inspect that evidence myself.

## Citations vs provenance

Citations are not provenance. The two systems answer different questions:

- **Provenance** tracks, via Claims, _who asserted_ a piece of data into the project — a user or an ingest run. See [Provenance.md](Provenance.md).
- **Citations** track _what external evidence_ supports a Claim.

Consequently, citation sources are **not claims-controlled**. Unlike user-inputted catalog fields, citation sources are edited directly through the API and admin, not through the claims workflow. (The link _from_ a claim to its evidence is provenance's concern — see below.)

## Data model

```text
Markdown passage or scalar claim
  └── `CitationInstance`        (one use of a source, with a locator)
        └── `CitationSource`    (the work or evidence object)
              └── `CitationSourceLink`(s)   (ways to inspect the source)
```

### CitationSource

A `CitationSource` is the shared work or evidence object — a book, a magazine, a web page, a database record. It is a **shared record**: when many pages cite the same book they should normally point at the same source, which is what makes deduplication and consistent presentation possible.

Sources may be **hierarchical** via a self-referential parent, when the domain needs it: work → edition, publication → issue → article, web root → child page. The hierarchy represents source _identity_, not locator position. Children do not inherit fields from their parent — prefill in the UI is fine, inheritance in the data is not.

A source carries a pragmatic `source_type` (book / magazine / web). Its job is to drive product behavior — search, edit fields, locator prompts, rendering — not to be a bibliography ontology, so the taxonomy stays small and grows only when a new type needs distinct behavior.

For source families with structured identifiers, two paired fields express the scheme:

- `identifier_key` — the scheme, set on a **root** source only (e.g. an IPDB or OPDB root). A root is a scheme-holder.
- `identifier` — the structured value within that scheme, set on a **child** only (e.g. IPDB machine `4443`). A child is a value-holder.

A source is a scheme-holder _or_ a value-holder, never both. Children with identifiers are unique within their parent. A web child sets `skip_locator` — its URL _is_ the locator, so the authoring UI skips the locator step.

### CitationInstance

A `CitationInstance` is a single use of a source in a specific place, usually with a locator (page, timestamp, section, fragment). Instances are **not shared** across usages: changing a locator should produce a new instance plus an ordinary edit, not mutate history in place.

`CitationInstance` lives in the **provenance app**, not the citation app — it is the join between a claim or passage and the evidence that supports it, so it belongs with the attribution machinery. The citation app owns the source records; provenance owns their _use_.

The text uses **point citations**, not text ranges. An inline marker sits at a position and means "this source supports the nearby claim", usually the preceding sentence. Ranges look more precise but demand discipline contributors won't sustain and produce misleadingly precise markup.

### CitationSourceLink

A `CitationSourceLink` is a reader-facing access point — a canonical URL, an archive URL, an uploaded scan, a museum-hosted copy. Links are ways to _inspect_ a source, not separate sources. They are wholly owned by their source.

Each link carries a `link_type`, and one value is load-bearing: **`homepage` marks a source's own root page and is the signal recognition's domain match keys off** (step 3 below), so it belongs only on a true root. Every other type (`reference`, `archive`, …) is a plain access point with no recognition role. A specific page minted under a root — a cited article, a forum thread — must be `reference`, never `homepage`, or domain matching would later mistake that one page for the whole domain's root.

## Authoring model

Citation authoring stays cheap at the moment of editing — Wikipedia's verification loop without the bureaucracy. The `[[` autocomplete is the front door; contributors don't pick a separate citation mode first. The same input accepts search text or pasted evidence (a URL or ISBN).

Reuse is primary but never gating: **centralization assists citation reuse, it does not gate citation authoring.** Shared sources are the long-term model and duplicate detection matters, but perfect deduplication isn't a prerequisite for saving — cleanup and merging can happen later.

## Recognition and extraction

When a contributor pastes evidence, the system tries to reuse an existing source first and only then helps create a new one. There are two layers with different trust models and performance profiles. Both produce a draft or a pointer for the contributor to confirm — neither silently auto-creates from low-confidence input.

### Recognition — local, fast

Recognition maps input to **existing data** using local DB queries only, with no external HTTP. It is folded directly into the search endpoint so typeahead stays fast. `recognize_url` resolves in three steps of decreasing confidence:

1. **Extractor match** — the URL matches a known scheme; an `Extractor` extracts and validates the identifier, then looks up the root and existing child. High confidence: one-click child creation is appropriate.
2. **Full-URL child-link match** — the URL exactly matches a stored child link. High confidence: re-citation of a known page.
3. **Domain match** — the hostname matches a root source's homepage link. Lower confidence: this suggests parent _reuse_ only, so the UI pre-selects the parent but still asks for child details.

The schemes live in an extractor registry keyed by `identifier_key` (currently IPDB and OPDB). Each `Extractor` knows how to pull an identifier from a URL, validate a bare identifier and build the canonical URL.

Two idempotent helpers, `get_or_create_external_source` (scheme + identifier) and `get_or_create_web_source` (raw URL), are the entry points catalog ingestion and data patches use to attach evidence. The web helper runs the same `recognize_url`, so a URL reuses an existing child or nests a new child — with a `reference` link, never `homepage` — under a domain-matched root. A URL whose domain matches no seeded root **raises** rather than minting a parentless source: a root web source is an abstract container, not directly-citable evidence, so the author must seed the website root first. They get-or-create rather than plain-create (the create API 422s on a duplicate), so re-applying a patch never duplicates. For the `cite:` authoring forms — `scheme:identifier` versus a bare URL, and why a scheme URL is rejected — see [DataPatches.md](DataPatches.md).

### Extraction — external, slow

Extraction fetches **new metadata from external services** and proposes a draft source for confirmation. Because it does external HTTP with variable latency and multiple failure modes, it is a **separate endpoint** from search, never folded into the search response — search must stay fast and must not degrade when an external service is down.

Implemented today:

- **ISBN → Open Library** — classify the input, look up locally, then cache, then the Open Library API; returns a draft (or an existing match the text search missed).
- **Generic URL → page metadata** — fetch the page and parse `<title>` / Open Graph tags into a sparse draft.

The result is always one of: a draft, an existing match, or a structured failure (`not_found`, `timeout`, `parse_error`, …). Extraction produces a **draft, not an auto-create** — external-service confidence is lower and editorial review has value. (This draft-first rule is specific to extraction; recognition resolving to validated local data can be one-click.)

### SSRF safety

Generic URL fetching goes through a guarded fetch that validates the target **by resolved IP, not by hostname**. It resolves DNS before connecting and checks that the resolved IP is globally routable, which closes the DNS-rebinding window and catches internal hosts (they resolve to private IPs) without a fragile hostname blocklist. Only `http`/`https` are allowed, redirects are re-validated each hop, and a wall-clock deadline bounds the whole chain. This applies to the generic URL fallback, not to hardcoded known-API endpoints like Open Library.

## Seeding

Heavily reused source families are pre-seeded so autocomplete is useful from the start and contributors don't recreate the same records. Seed data is grouped by kind (books, magazines, websites) and applied through an idempotent upsert that creates or updates sources and reconciles their links, so reseeding is safe. Pre-seeding is especially worthwhile for bounded pinball-specific corpora — major books, magazines, manuals and database sites.

## Reader experience

On read, inline citations render as superscript references and a page with any citations shows a references section. Each entry shows the source, the locator and any useful access links. Scalar-claim citations and inline citations surface as one coherent evidence list. Pages with no citations are allowed — citations improve trust and maintainability but are not a prerequisite for contribution.

## Authorization

All mutating citation routes — create, update, extract, link management — are gated by the `CITATION_EDIT` activity, and the extract endpoint is additionally throttled to bound external-service abuse. See [Authz.md](Authz.md) for how activity gates work.

## Not yet built

- DOI → publication metadata extraction (ISBN and generic URL are done).
- Richer generic-URL extraction beyond title / Open Graph tags.
