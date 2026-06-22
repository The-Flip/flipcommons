# Citation Autogeneration Design

This document describes the planned automatic source-draft flow for citations. It is intentionally future-facing: parts of it have not been implemented yet.

## Status

This project has a backend recognition layer (built April 2026) that handles:

- **Extractor registry** (`backend/apps/citation/extractors.py`): URL pattern matching and identifier validation for IPDB, OPDB, and future schemes. Keyed by `CitationSource.identifier_key`.
- **Search recognition**: the `/api/citation-sources/search/` endpoint recognizes pasted URLs (extractor match, full URL child-link match, recognition-host match) and returns structured recognition metadata alongside search results.
- **Identifier-based child creation**: the create endpoint validates identifiers through extractors, auto-builds canonical URLs and child names.
- **DB-level deduplication**: `CitationSource.identifier` field with `UNIQUE(parent, identifier)` constraint prevents duplicate children.

The **extraction layer for external metadata lookups** — calling external services and returning proposed `CitationSource` drafts for confirmation — is now partially built: ISBN → Open Library and generic URL → page-metadata drafts exist. DOI resolution and richer URL extraction remain future work.

## Goal

Citation entry should accept evidence-like input such as:

- ISBN
- DOI
- known-site URL
- generic URL

If search does not find an existing source, this project should try to turn that evidence into a proposed new source draft instead of forcing the contributor into manual data entry.

The important constraint is that this should help source creation, not silently bypass editorial review.

## Product Shape

The intended flow is:

1. User searches or pastes evidence into the citation input.
2. This project searches for an existing source first.
3. If there is no strong existing match and the input looks like evidence, this project runs extraction.
4. Extraction returns either:
   - a proposed source draft
   - an existing-source match
   - a structured failure
5. The user confirms or edits the draft before creation.

## Two-Tier Architecture: Recognition vs Extraction

The system has two distinct layers with different trust models, performance profiles, and UX treatments.

### Recognition (implemented)

Recognition maps user input to **existing data** using local DB queries only. No external HTTP, no latency risk, no failure modes beyond normal DB availability.

Pipeline: `raw input → pattern match → existing source pointer`

Integrated directly into the `/search/` endpoint. Returns a `Recognition` alongside search results in the same response. Three resolution steps:

1. **Extractor match** — URL matches a known scheme (IPDB, OPDB), extracts an identifier, looks up existing parent and child.
2. **Full URL child-link match** — exact URL match against stored **child** source links.
3. **Recognition-host match** — the hostname resolves to a root via its `CitationSourceRootDomain`, an owned recognition host on the root (longest label-boundary suffix wins, so subdomains collapse to the owning root). This keys off `CitationSourceRootDomain`, **not** `link_type` and **not** the homepage link — recognition is decoupled from display links so editing a homepage URL never changes matching.

These three steps have different confidence levels:

- **Extractor match** and **child-link match** resolve to validated identifiers or exact known URLs. One-click child creation is the right UX here — the identifier is validated locally, the parent is known, the canonical URL is deterministic. No draft/confirm step needed.
- **Recognition-host match** returns only a parent pointer with no identifier. This is **suggested parent reuse**, not one-click creation — the UI should pre-select the parent but still require the user to fill in child details. The cited record is always a child page under the root; the abstract root itself is never a citation target.

### Extraction (partially implemented)

Extraction fetches **new metadata from external services** and proposes a draft source for user confirmation. External HTTP, variable latency, multiple failure modes. ISBN → Open Library and generic URL → page-metadata drafts are built; DOI resolution remains future work.

Pipeline: `raw input → classify → external fetch → normalize → CitationSource draft`

Must be a **separate endpoint** from search (`POST /api/citation-sources/extract/`), not folded into the search response. Reasons:

- Search must stay fast (~50ms) for typeahead. External HTTP adds 500ms–3s.
- Extraction is an explicit user action ("look up this ISBN"), not an implicit side-effect of typing.
- Failure in extraction must not degrade search.

The intended UX sequence:

1. Search returns results + recognition (fast, local).
2. If nothing useful matches, the UI offers "Look up this URL/ISBN."
3. User clicks that, triggering the extract endpoint (slow, external).
4. Response is a draft the user confirms or edits before creation.

## Design Principles

### Backend, not frontend

The extraction layer should live on the Django side, not in the Svelte UI.

Reasons:

- external HTTP belongs on the server
- rate limiting and caching belong on the server
- API keys, if any, belong on the server
- source creation and validation already live on the server

### Drafts, not auto-create

Extraction should produce a `CitationSource` draft, not silently create records. The user should still confirm or edit what will be saved.

This applies to **extraction** specifically — data from external services where confidence is lower and editorial review has value. It does not apply to extractor-based recognition or child-link re-citation, where the system resolves to known local data with validated identifiers (see "Recognition" above). Domain-only recognition already requires manual child details, so the principle is moot there.

### Known extractors first

Generic extraction is a weak fallback. Known identifiers and known sites should get dedicated extractors first.

Examples:

- ISBN -> book metadata
- DOI -> publication metadata
- `ipdb.org` URL -> site-specific source draft
- generic URL -> sparse fallback based on page metadata

### Reuse before creation

Extraction is not the first step. Search for an existing source should always run first. Extraction only helps when reuse fails.

## Extraction Endpoint Shape

The extract endpoint receives evidence and returns a draft:

```text
POST /api/citation-sources/extract/
{ "input": "<ISBN, DOI, or URL>" }

→ 200 { "draft": { ...CitationSource fields... }, "confidence": "high"|"low", "source_api": "openlibrary" }
→ 200 { "match": { "id": 42, "name": "..." } }
→ 200 { "draft": null, "match": null, "error": "not_found"|"timeout"|"parse_error" }
→ 422 { "detail": "Unsupported input" }
→ 429 (rate limit exceeded)
```

Lookup outcomes — draft found, existing match found, or lookup failed — use 200 with the result in the payload, because these are normal outcomes the UI needs to handle gracefully. Input validation errors (malformed/unsupported input) use 422. Rate limiting uses 429.

The `match` variant covers cases where extraction discovers an existing source that text search missed (e.g. ISBN normalization finds a match). The UI should treat this like a search result, not a draft.

## Operational Concerns

### Latency

External lookups add 500ms–3s per call. The extract endpoint should enforce a hard timeout (e.g. 5s) so the UI never hangs indefinitely. The UI should show a loading state during extraction.

### Caching

Not all metadata is equally volatile:

- **ISBN/DOI metadata** is stable. Cache aggressively — days to weeks. A Django cache key like `extract:isbn:{value}` is sufficient.
- **URL page titles** change. Cache shorter — hours. Stale titles are low-harm since the user edits before saving.

Use Django's cache framework. No need for a dedicated table unless cache hit rates prove insufficient.

### Rate limiting

Two layers:

- **Per-user throttle** on the extract endpoint (e.g. 10 requests/minute) to prevent abuse.
- **Per-source backoff** for external APIs with their own rate limits (e.g. Open Library). If a source returns 429, back off and return a structured failure rather than retrying in-request.

### Failure modes

External services fail. The extract endpoint should:

- **Fail fast** — timeout after 5s, no retries within the request cycle.
- **Return structured errors** — `"timeout"`, `"rate_limited"`, `"not_found"`, `"parse_error"`. The UI maps these to helpful messages.
- **Never block search** — extraction is a separate endpoint, so search is unaffected by external service outages.

Circuit breakers or retry queues are premature for the first implementation. If a source is down, the user falls back to manual entry.

### SSRF protection

Generic URL fetching must validate the target before making a request. The implementation lives in `backend/apps/citation/safe_fetch.py`.

**Approach: IP validation only, no hostname blocklist.** The module resolves DNS _before_ connecting and checks the resolved IP — not the hostname. This closes the DNS-rebinding TOCTOU gap (resolve once, connect to the validated IP). A separate hostname blocklist was considered and rejected: internal hostnames resolve to private IPs, which the IP check already catches; a hostname list would be fragile, incomplete, and redundant.

Validation rules:

- **Scheme**: only `http` and `https`. Reject `ftp`, `file`, `javascript`, etc.
- **Hostname**: must be non-empty.
- **Resolved IP**: must be `is_global` (Python `ipaddress` module). This blocks private, reserved, loopback, link-local, and documentation ranges in a single check. Multicast is blocked separately — Python considers multicast addresses `is_global` (they are globally allocated), but they are not unicast-routable and no legitimate web page lives at one.
- **Redirects**: up to 5 hops, each re-validated through the same IP check. Cross-scheme redirects (HTTPS → HTTP) are allowed but the new target's IP is still validated.
- **TLS**: connects to the resolved IP via plain TCP, then wraps with TLS using `server_hostname` for SNI and certificate validation against the original hostname.
- **Wall-clock deadline**: total timeout budget across all redirect hops, not per-hop.

This applies to the generic URL metadata fallback, not to known-API extractors (ISBN, DOI) which hit hardcoded external endpoints.

## First Useful Cases

The first high-value extraction targets, with current status:

- **IPDB/OPDB URL recognition** — implemented via extractor registry
- **Recognition-host source matching** — implemented via `CitationSourceRootDomain` (longest-suffix, subdomain-aware)
- **Full URL child-link matching** — implemented for re-citation of known pages
- **ISBN lookup for books** — implemented via Open Library
- **generic URL metadata fallback** — implemented (page `<title>` / Open Graph tags)
- DOI lookup for publications — not yet implemented

## Failure Behavior

Extraction failures should be normal and explicit.

If extraction fails, the user should get a clear next step:

- use an existing result if one was found
- continue with manual source creation
- revise the pasted input

The system should not make extraction feel magical or guaranteed.

## Relationship To Current Design

This design is a planned extension of the citation flow described in [CitationsDesign.md](CitationsDesign.md).

The recognition layer is complete and integrated into search. The extraction layer is partially built (ISBN and generic-URL drafts); DOI resolution and richer URL extraction are the remaining steps, and this document describes their intended shape.
