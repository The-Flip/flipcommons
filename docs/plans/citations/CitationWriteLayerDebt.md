# Citation Write-Layer Debt

This document tracks open citation write-layer debt.

## Open Debt

### D5 — Ingest-created citation sources are unattributed

Ingest-created `CitationSource` and `CitationSourceLink` rows can have `created_by` / `updated_by` set to null. Citation sources are not claims-controlled, so these rows also have no changeset attribution. That is intentional ingest semantics, but it means the system cannot answer who introduced an ingested source record.

This is separate from claim provenance. Claim provenance can say which ingest run asserted a catalog claim; it does not attribute the citation source row that was minted while resolving that claim's evidence.

### D6 — Recognition domains have no attribution fields

`CitationSourceRootDomain` has no `created_by` / `updated_by` fields. The recognition host is an important editorial fact because it controls URL routing, but it is not directly attributable on any path: admin, seed/upsert, or interactive root creation.

If citation-source gardening becomes contributor-facing, recognition-host attribution should be revisited alongside the gardening activities.

### D10 — Web children fragment on near-duplicate URLs

Web child reuse is keyed by exact raw URL string. The recognizer's child-link step and the web-source helper match `CitationSourceLink.url` exactly, so variants such as `http` vs `https`, trailing slash differences, and tracking parameters can mint separate children under the same root.

The likely fix is a normalized child identity-URL table, analogous to `CitationSourceRootDomain` at the root level. That work is described at a higher level in [CitationInstanceUrls.md](CitationInstanceUrls.md).

### D11 — Exact child-link recognition can be nondeterministic

`CitationSourceLink.url` is unique per source, not globally unique. The same URL can exist on children under different roots, and recognition takes the first matching child link. That means recognition can depend on query ordering instead of a declared identity rule.

A normalized, globally unique child identity-URL table would also close this. Duplicate child links are a cleanup/gardening concern until that table exists.

### D16 — Extraction and create schemas overlap

The extraction draft schema, root/create schema, and `cite-url` schema describe overlapping pieces of the same citation-source draft. The frontend maps between those shapes by hand.

`extra="forbid"` catches some stale fields at the API boundary, but it is not a shared contract. A future extraction-shape change can require coordinated client updates across multiple manually-mapped schemas.

### D17 — Extraction draft cache versioning is manual

Extraction results are cached under hand-maintained `extract:v2:*` keys. Any incompatible draft-shape or semantics change requires a deliberate cache namespace bump. Forgetting the bump can serve stale cached drafts with old semantics.

This is latent because extraction drafts are confirm-before-create, but the cache version is a manual contract.

### D18 — Search, extraction, and finalize can recognize different worlds

Search recognition, extraction, and `cite-url` finalization each recognize against current database state at their own request time. If a more-specific root is added between search/extraction and finalize, the final page can nest under a root the contributor was not shown.

Server-side re-recognition is the right trust boundary; the open question is whether the UI should surface a "destination changed" warning when finalize resolves differently than the earlier recognition result.

### D19 — Abstract roots are not rejected at citation-instance creation

The normal citation flows steer contributors toward concrete children, and URL citation structurally resolves to a child under a root. But the low-level `create_citation_instance` endpoint can create an instance pointing directly at a parentless web or magazine root if given that source id.

If direct citation-instance creation is a public authoring surface, it should reject abstract roots using the same `is_abstract` / source-type trait facts the search UI already exposes.

## Related Future Work

The larger `CitationInstance` rework is split across three docs: [CitationInstanceQuotes.md](CitationInstanceQuotes.md) (`quote`, retiring `Claim.citation`), [CitationInstanceReferences.md](CitationInstanceReferences.md) (content-addressed identity and how claims reach evidence) and [CitationInstanceUrls.md](CitationInstanceUrls.md) (`access_url` and the normalized child identity-URL table). That work overlaps with D10/D11 if it introduces the identity-URL table, but it is broader than this write-layer debt list.
