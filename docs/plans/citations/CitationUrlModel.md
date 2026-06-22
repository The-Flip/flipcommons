# Citation URL model

## Context

The Citation system doesn't model URLs super cleanly. We should probably model them more like Wikidata. We already follow **Wikidata's normalized shape**: we already has the shared-entity (`CitationSource`) + per-use (`CitationInstance`) split that Wikidata models as an Item + a reference block, so the move is to make `CitationInstance` a proper reference block.

## The URL model

### Types of 🔗 URLs

There should be three distinct kinds of URLs:

- **Identity URLs**: where the WORK canonically lives
- **Access URLs**: URL actually consulted for a claim
- **Archive URLs**: snapshot of the access URL

#### 🔗 Identity URL

Identity URL is where the WORK canonically lives (homepage, IPDB/catalog page):

- Lives on: the parent source (CitationSource)
- Cardinality: 0..n, shared by every claim that cites the work
- Analog: Wikidata P856 (official website) on the source Item
- Dependency-wise, identity is independent and exists separately from the other types of URLs

#### 🔗 Access URL

Access URL is the SPECIFIC COPY actually consulted for this claim (this scan, this mirror, this edition):

- Lives on: the per-claim citation instance (CitationInstance)
- Cardinality: 0..1 per instance
- Analog: Wikidata P854 (reference URL) inside the reference block
- A print book/magazine read on paper has NO access URL
- For a born-digital web page with no separable work identity, the URLs _often_ collapse: identity = access = the same URL. But not always: when a contributor cites an `archive.org` snapshot because the live page is gone or no longer has the old content, access (the Wayback URL) differs from identity (where the work lived). The per-instance access field carries that difference; do not assume web always collapses
- Dependency-wise, access is a manifestation of the work (the identity entity, which always exists), but does not require an identity URL — a source may have an access URL and zero identity URLs (e.g. a page cited only via its archive.org snapshot, with no recorded canonical home).

#### 🔗 Archive URL

Archive URL is a frozen snapshot (e.g. Wayback) of the ACCESS URL:

- Lives on: hangs off the access URL (per instance)
- Cardinality: 0..1, only if there is an access URL
- Analog: Wikidata P1065 (archive URL), which archives P854 — never P856
- You archive the COPY you read (access), NOT the abstract "where the work lives" page (identity)
- A print book/magazine read on paper has NO access URL, therefore NO archive URL
- Dependency-wise, archive depends on access; archive is meaningless without an access URL

## Prior art

### FRBR

This mirrors the library-science FRBR ladder: identity URL ≈ Work, access URL ≈ Manifestation/Item, archive URL ≈ fixity copy.

## Data model

Something like this:

```text
CitationSource (root)
    identity URL: https://website.com/
    CitationSource (child)
         identity URL: https://website.com/somePage
         CitationInstance
            access URL: could be https://website.com/somePage or https://web.archive.org/web/20150214032023/http://website.com/somePage if that's where the user actually read it and they pasted in that URL.
```

In the case of `CitationInstance` using archive.org, the URL is of a known format that contains the original page URL. That's how we recognize and attribute to the correct CitationSource.

## How the system changes

Flipcommons today models the consulted web page as a child `CitationSource` entity (`recognize_url` resolves to that child, `create_web_child` mints it) — and we **keep** that. The child is the reusable record: its metadata (Title, author, year) and its identity URL live in one place, so an already-cited page is re-cited without re-entering any of it. The change is **additive** — the per-use access URL moves onto the `CitationInstance`, where today the consulted/archive URL is shoehorned onto the source as a link.

Adopting the model means:

- **Children stay; the access URL is additive.** A cited page remains a child `CitationSource` (its metadata + identity URL); a new per-use **access URL** is recorded on the `CitationInstance`. `recognize_url` still resolves a pasted page URL to its child, and `create_web_child` still mints one for a page not yet seen. (Print/magazine never had page children — the access URL is simply new there too.)
- **Recognition keys off a normalized identity-URL table.** This is the structural change that makes both reuse and dedup work — see [Recognition](#recognition-a-normalized-identity-url-table) below.
- **Recognition must peel archive URLs (the `via` problem).** A pasted `web.archive.org/web/<timestamp>/website.com/somePage` has host `web.archive.org`, not the page's own host, so a naive match resolves to the wrong source (or none). `recognize_url` strips the Wayback timestamp prefix, recovers the **embedded** original URL, and recognizes _that_ (→ the existing child), while the stored access URL on the instance stays the archive.org URL actually consulted. Same pattern as Wikipedia's `via` (the deliverer ≠ the work). This only works for archive formats that **embed** the original (Wayback, archive.today long-form); an opaque `archive.org/details/<id>` carries no original URL, so its access URL is **declared** against a separately-identified page, not recognized.

### Recognition: a normalized identity-URL table

Recognizing a page by its identity URL needs the URL stored in **normalized** form, and the architecture already has the exact precedent: `CitationSourceRootDomain` is a normalized recognition table for **hosts** (root level, suffix-matched). The child analog is the same pattern one rung down — a table of **normalized full identity URLs** (child level, exact-matched):

- **Normalize at write time in `clean()`** (lowercase host, strip `www.`, force `https`, drop a trailing slash and tracking params), exactly as `CitationSourceRootDomain.host` is normalized today.
- **A global `unique` constraint on the normalized URL is the dedup.** Two children can't claim the same canonical page, so duplicate-page fragmentation can't happen and cross-root ambiguity is structurally impossible — the same way the unique `host` works for roots. (These are debt items D10/D11 in the write-layer audit, structurally closed rather than patched.)
- **Decoupled from the display link**, for the same reason `CitationSourceRootDomain` was split out from the homepage link: keying recognition off the raw display URL re-couples recognition to display edits, and you can't index a canonicalized match without storing the canonical form.

The recognition pipeline end to end:

1. scheme extractors (IPDB/OPDB/YouTube) — unchanged
2. peel archive → recover the embedded original URL (Wayback / archive.today long-form)
3. canonicalize
4. exact match on the normalized identity-URL table → the **child** (reuse its metadata)
5. host-suffix match on `CitationSourceRootDomain` → the **root** (mint/declare a page under the site)

The pasted access URL is stored verbatim on the `CitationInstance`; only the recognition _key_ is peeled and canonicalized.

## v1 scope

Only the access tier is built in v1. The archive tier is deferred wholesale, and the access _date_ needs no new field.

### In — access URL on the instance

- **Access URL → `CitationInstance`** (per-use). This is the one load-bearing v1 decision: it's the row the archive tier later hangs off, so getting it on the instance is what makes archive a clean additive migration rather than a rework.
- **Access date = the existing `CitationInstance.created_at`** (`auto_now_add`). No `accessed_at` field. For an interactive cite, the row is minted at the moment of consultation, so `created_at` _is_ the access date. Caveat (note, don't fix): `created_at` is mint time, which diverges from true access time for **ingest** (stamped at patch-apply, not consultation — see Deferred) and **re-cites** (`CitationInstance` is immutable, so a correction mints a fresh row). Good enough for v1; revisit only if precise access-date semantics ever matter.
- **A human-pasted `archive.org` URL is just an access URL — needs no archive machinery.** Citing a dead page via its Wayback snapshot means the access URL happens to point at archive.org; it's a plain string in the access field. This is distinct from the deferred archive _tier_ (a bot-derived snapshot of a live access URL, with its own `archive_url`/date/`url-status`). So v1 can support archive-cited pages with **no new columns** — but **not** "with nothing extra": its one prerequisite, the Wayback-peeling in recognition (see [How the system changes](#how-the-system-changes)) that lets the URL resolve to the right child or root, is **unbuilt today** (`recognize_url` has no Wayback parsing; extraction fetches archive.org's own page instead of recovering the embedded original — see [CitationSystemAudit.md](CitationSystemAudit.md)). Until that peeling lands, a pasted `archive.org` URL stores fine as an access string but recognizes against `web.archive.org`, not the page's host. Archive-cited pages are therefore a small additive follow-up, not a day-one freebie.

### Deferred

#### Data patch access timestamps

Deferred. For a patch-sourced citation, `created_at` is the apply time, not when the data patch author actually consulted the URL — so it's a fabricated access date, and it shifts on every dev rebuild (patches re-apply against a fresh DB). v1 accepts that; patch citations simply have no reliable access date.

The eventual fix: make the access date **settable** on the single write path so a patch's `cite:` can carry the author's real consultation date, but **default it to the `CitationInstance`'s own timestamp** — a separate field with a `Now()` `db_default` is fine (it equals `created_at` at mint, so the default needs no cross-field copy). Interactive cites take the default; patches override it when they supply a date. This is the field the v1 "no new column" decision defers, not a never.

#### The entire archive tier

Deferred. On Wikipedia and Wikidata, archive URLs and archive dates are **machine-stamped, not hand-typed** — InternetArchiveBot adds `archive-url`/`archive-date`/`url-status=dead` after a link rots; Citoid auto-fills access-date. We will do the same, and v1 builds **none** of it:

- no `archive_url` / `archived_at` columns
- no Wayback submission at cite time
- no dead-link detection / sweep
- no `url-status` (live/dead/usurped) toggle or "render archive instead of access" logic

This defers cleanly **because** access lives on the instance: archive depends only on access (archive → access, one-way), so adding the archive columns + the bot machinery later is a pure additive migration on the same row, with no v1 rework. Building the lower rung now and the upper rung never (in v1) is structurally sound.
