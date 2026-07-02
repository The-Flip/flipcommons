# Citation Instance URLs

## Context

The Citation system doesn't model URLs super cleanly. We should probably model them more like Wikidata. We already follow **Wikidata's normalized shape**: we already have the shared-entity (`CitationSource`) + per-use (`CitationInstance`) split that Wikidata models as an Item + a reference block, so the move is to make `CitationInstance` a proper reference block.

This plan completes the reference block by adding the access URL — the specific copy consulted — as part of the evidence, mirroring Wikidata's reference URL (P854).

## The URL model

### Three kinds of URLs

- **Identity URL**: where the work canonically lives
- **Access URL**: the specific copy actually consulted for a claim
- **Archive URL**: a snapshot of the access URL

#### 🔗 Identity URL

Where the work canonically lives (homepage, IPDB/catalog page):

- Lives on: the Citation Source
- Cardinality: 0..n, shared by every claim that cites the work
- Analog: Wikidata P856 (official website) on the source Item
- Identity is independent: it exists separately from the other URL kinds

#### 🔗 Access URL

The specific copy actually consulted for this claim (this scan, this mirror, this edition):

- Lives on: the Citation Instance, as part of its identity
- Cardinality: 0..1 per instance
- Analog: Wikidata P854 (reference URL) inside the reference block
- A print book or magazine read on paper has no access URL
- For a born-digital web page with no separable work identity, the URLs _often_ collapse: identity = access = the same URL. But not always: a contributor may cite an `archive.org` snapshot because the live page is gone or no longer has the old content, so access (the Wayback URL) differs from identity (where the work lived). The per-instance access field carries that difference; web does not always collapse.
- Access is a manifestation of the work, but does not require an identity URL — a source may have an access URL and zero identity URLs (e.g. a page cited only via its archive.org snapshot, with no recorded canonical home).

#### 🔗 Archive URL

A frozen snapshot (e.g. Wayback) of the access URL:

- Lives on: hangs off the access URL (per instance)
- Cardinality: 0..1, only if there is an access URL
- Analog: Wikidata P1065 (archive URL), which archives P854 — never P856
- You archive the copy you read (access), not the abstract "where the work lives" page (identity)
- A print book or magazine read on paper has no access URL, therefore no archive URL
- Archive depends on access; archive is meaningless without an access URL

## Prior art

### FRBR

This mirrors the library-science FRBR ladder: identity URL ≈ Work, access URL ≈ Manifestation/Item, archive URL ≈ fixity copy.

## Data model

```text
CitationSource (root)
    identity URL: https://website.com/
    CitationSource (child)
         identity URL: https://website.com/somePage
         CitationInstance
            access URL: https://website.com/somePage, or
            https://web.archive.org/web/20150214032023/http://website.com/somePage
            if that is the snapshot the contributor actually read and pasted.
```

When a Citation Instance's access URL points at archive.org, the URL has a known format that embeds the original page URL. That embedded URL is how recognition attributes the instance to the correct Citation Source.

## How the system changes

A consulted web page is modeled as a child Citation Source: its metadata (title, author, year) and identity URL live in one place, so an already-cited page is re-cited without re-entering any of it. `recognize_url` resolves a pasted page URL to its child, and `create_web_child` mints one for a page not yet seen. The change is **additive** — the per-use access URL is recorded on the Citation Instance.

Adopting the model means:

- **Children stay; the access URL is additive.** A cited page remains a child Citation Source (its metadata + identity URL); a new per-use **access URL** is recorded on the Citation Instance. `recognize_url` resolves a pasted page URL to its child, and `create_web_child` mints one for a page not yet seen. (Print and magazine sources have no page children — the access URL is simply new there too.)
- **Recognition keys off a normalized identity-URL table.** This is the structural change that makes page reuse work and prevents duplicate children — see [Recognition](#recognition-a-normalized-identity-url-table) below.
- **Recognition peels archive URLs (the `via` problem).** A pasted `web.archive.org/web/<timestamp>/website.com/somePage` has host `web.archive.org`, not the page's own host, so a naive match resolves to the wrong source (or none). `recognize_url` strips the Wayback timestamp prefix, recovers the **embedded** original URL and recognizes _that_ (→ the existing child), while the stored access URL on the instance stays the archive.org URL actually consulted. Same pattern as Wikipedia's `via` (the deliverer ≠ the work). This works only for archive formats that **embed** the original (Wayback, archive.today long-form); an opaque `archive.org/details/<id>` carries no original URL, so its access URL is **declared** against a separately-identified page, not recognized.

### Recognition: a normalized identity-URL table

Recognizing a page by its identity URL needs the URL stored in **normalized** form, and the architecture has the exact precedent: `CitationSourceRootDomain` is a normalized recognition table for **hosts** (root level, suffix-matched). The child analog is the same pattern one rung down — a table of **normalized full identity URLs** (child level, exact-matched):

- **Normalize at write time in `clean()`** (lowercase host, strip `www.`, force `https`, drop a trailing slash and tracking params), exactly as `CitationSourceRootDomain.host` is normalized.
- **A global `unique` constraint on the normalized URL prevents duplicate children.** Two children can't claim the same canonical page, so duplicate-page fragmentation can't happen and cross-root ambiguity is structurally impossible — the same way the unique `host` works for roots. This closes write-layer debt items D10/D11 ([CitationWriteLayerDebt.md](CitationWriteLayerDebt.md)) structurally rather than patching them.
- **Decoupled from the display link**, for the same reason `CitationSourceRootDomain` is split from the homepage link: keying recognition off the raw display URL re-couples recognition to display edits, and a canonicalized match needs the canonical form stored to be indexable.

The recognition pipeline end to end:

1. scheme extractors (IPDB/OPDB/YouTube)
2. peel archive → recover the embedded original URL (Wayback / archive.today long-form)
3. canonicalize
4. exact match on the normalized identity-URL table → the **child** (reuse its metadata)
5. host-suffix match on `CitationSourceRootDomain` → the **root** (mint/declare a page under the site)

The pasted access URL is stored verbatim on the Citation Instance; only the recognition _key_ is peeled and canonicalized.

## v1 scope

v1 builds the access tier. The archive tier is deferred wholesale, and the access _date_ needs no new field.

### In — access URL on the instance

- **Access URL → Citation Instance**, a field on the evidence row. This is the one load-bearing v1 decision: it's the row the archive tier later hangs off, so getting it on the instance is what makes archive a clean additive migration rather than a rework.
- **Access date = the Citation Instance's `created_at`** (`auto_now_add`). No `accessed_at` field. For an interactive cite that mints fresh evidence, the row is created at the moment of consultation, so `created_at` _is_ the access date. Caveat: `created_at` is first-seen time, which diverges from true access time for **ingest** (stamped at patch-apply, not consultation — see Deferred). Good enough for v1; revisit only if precise access-date semantics ever matter.
- **A human-pasted `archive.org` URL is just an access URL — it needs no archive machinery.** Citing a dead page via its Wayback snapshot means the access URL happens to point at archive.org; it's a plain string in the access field. This is distinct from the deferred archive _tier_ (a bot-derived snapshot of a live access URL, with its own `archive_url`/date/`url-status`). So v1 supports archive-cited pages with **no new columns**, but **not** "with nothing extra": its one prerequisite is the Wayback-peeling in recognition (see [How the system changes](#how-the-system-changes)) that lets the URL resolve to the right child or root. Until that peeling lands, a pasted `archive.org` URL stores fine as an access string but recognizes against `web.archive.org`, not the page's host. Archive-cited pages are therefore a small additive follow-up, not a day-one freebie.

### Deferred

#### Data patch access timestamps

For a patch-sourced citation, `created_at` is the apply time, not when the data patch author actually consulted the URL — so it's a fabricated access date, and it shifts on every dev rebuild (patches re-apply against a fresh DB). v1 accepts that; patch citations simply have no reliable access date.

The eventual fix records the author's real consultation date for patch citations via the `cite:` block, since `created_at` is apply-time, not consultation-time. The settable date would live on the citing claim (or its `ChangeSet`), defaulting to the changeset's timestamp and overridden by the patch's `cite:`.

#### The entire archive tier

On Wikipedia and Wikidata, archive URLs and archive dates are **machine-stamped, not hand-typed** — InternetArchiveBot adds `archive-url`/`archive-date`/`url-status=dead` after a link rots; Citoid auto-fills access-date. We will do the same, and v1 builds **none** of it:

- no `archive_url` / `archived_at` columns
- no Wayback submission at cite time
- no dead-link detection / sweep
- no `url-status` (live/dead/usurped) toggle or "render archive instead of access" logic

This defers cleanly **because** access lives on the instance: archive depends only on access (archive → access, one-way). The archive tier is machine-stamped onto evidence that already exists, so it attaches as a separate annotation keyed off the access URL rather than as columns on the immutable evidence row — a snapshot of a page is metadata about the consulted copy, not a new piece of evidence. Adding it later is a pure additive migration with no rework.

## Data patch shape

The per-use access URL adds an `access_url` to the `cite:` block defined in [CitationInstanceQuotes.md](CitationInstanceQuotes.md):

```yaml
cite:
  url: https://example.com/source-page
  locator: Optional section or page
  quote: Exact quoted source text
  access_url: Optional consulted URL when it differs from the source identity URL
```

`access_url` records the consulted copy, so a cite that consulted a different copy records a different `access_url`.
