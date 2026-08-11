# Citation root paths

Path-scoped citation roots.

## Problem

URL citations currently resolve to their owning `CitationSource` by hostname alone: `urlparse(url).hostname` → `normalize_host` → longest label-boundary suffix match against `CitationSourceRootDomain` rows (`backend/apps/citation/hosts.py`, `longest_suffix_match`). The path of the URL never participates, and `CitationSourceRootDomain.host` is globally unique (`backend/apps/citation/models.py`, ~line 607).

This makes documents on shared multi-tenant CDN hosts uncitable. The forcing case: Cardona Pinball Designs (`GoDaddy Website Builder site, cardonapinball.com`) publishes its first-party documents — release-notes PDFs, instruction-card JPGs — only on GoDaddy's shared CDN, e.g.:

`https://img1.wsimg.com/blobby/go/4bd466e8-edb0-49f6-afcc-31250ba5b0f3/downloads/FT%20release%202026%2006%2012.pdf`

The path segment `4bd466e8-edb0-49f6-afcc-31250ba5b0f3` is Cardona's stable GoDaddy tenant UUID. Registering the bare host `img1.wsimg.com` is forbidden and must stay forbidden: it would attribute every GoDaddy customer's files to one maker, and host uniqueness would block the next maker from ever registering it. Unlike Shopify (which mirrors CDN files under the store's own domain — how the flippatch 0221 Sonic campaign solved this), GoDaddy has no maker-domain mirror (probed both plausible URL shapes on cardonapinball.com: 404).

Context: this arises from the flippatch 2026-enrichment campaign, `~/dev/flippatch/campaigns/0215-frontier-2026/RULEBOOK.md` → "Citation roots" documents the current shared-host restraint ("documentation, not enforcement") for `img1.wsimg.com`, `cdn.shopify.com`, `storage.googleapis.com`. The fish-tales family patch is blocked on citing Cardona's release notes.

## Grounding instructions

Get grounded on the relevant code, such as `backend/apps/citation/hosts.py`, `models.py` (`CitationSourceRootDomain`), `source_upsert.py`, `deliverers.py`, `extractors.py`, `docs/Citations.md`, `docs/CitationDomainGovernance.md`. Understand how recognition, the patch sources block, and the deliverer guard interact, and check for prior art or plans around path-aware recognition. Consider edge cases: percent-encoding/normalization of paths, querystrings, archive: interplay, migration of existing rows, and what the admin/API surfaces need.

## AI analysis

This analysis and proposed design has not been vetted by the user.

### How recognition works today

**Read path**: `backend/apps/citation/extractors.py:199` parses `urlparse(url).hostname` → `normalize_host` → queries `CitationSourceRootDomain` rows whose host is in `label_suffixes(host)` → `longest_suffix_match` picks the most specific. The full URL is in hand at that point — the path is simply never consulted. Structurally, adding path participation is contained: one recognizer, one pure-helper module, one model.

**Purity layering is strict and worth preserving**: `hosts.py` is dependency-free pure string ops (Host NewType pins normalize-before-compare at the type level); `psl.py` isolates the PSL; import-linter keeps the read path PSL-free. A path-prefix matcher belongs in `hosts.py` with a sibling `PathPrefix` NewType and a `normalize_path_prefix` chokepoint.

**Write paths all funnel through `clean()`**: admin inline (the sole interactive edit surface), patch declare (source_upsert full_cleans throwaway instances at read phase and real rows at mint), and cite-url's funnel. The deliverer guard in clean() (deliverers.py) is the exact precedent for "declared host table consulted at write time, app-level because suffix-matching a table isn't portable DDL."

**Patch-side resolution** is exact-host, never suffix: `_roots_owning_hosts` / `_ensure_root_domains` in `source_upsert.py` key on the literal host for identity resolution and additive minting. These become exact `(host, path_prefix)` lookups — a mechanical change.

**Prior art**: `CitationDomainGovernance.md` (G1–G5, all shipped) is the direct ancestor; its "Out of scope" already names third-party CDN hosts as the known limitation this design fills. No existing plan covers path-aware recognition.

### Latent hazards

The domains: parser silently drops paths. `_declared_domains_hosts` does `urlparse(entry).hostname` or entry — a well-meaning patch author declaring `img1.wsimg.com/blobby/go/<uuid>` today would silently register bare `img1.wsimg.com`, the exact catastrophe the RULEBOOK warns about. The path-carrying form isn't just a feature; it converts this silent foot-gun into either meaning or a clean error.

The cite-url funnel will mint a shared-CDN root from contributor paste. `wsimg.com` is not a public suffix, so an unrecognized img1.wsimg.com/... paste in the interactive flow rounds to registrable domain and mints a `wsimg.com` site root today. The shared-host list needs to gate the funnel (`HostRejection.SHARED_HOST` → 422 with a teaching message), not just `clean()`.

### Proposed design

**Model**. CitationSourceRootDomain gains path_prefix (CharField, default '', never NULL — empty string keeps the unique constraint honest across backends). unique=True on host becomes UniqueConstraint(host, path_prefix). Migration is trivial: all existing rows get '' and behave identically. clean() normalizes the prefix (require leading /, strip trailing /, reject ?/#/empty segments) and enforces the shared-host rule.

**Matching**. In hosts.py: RootDomainMatch grows path_prefix; the matcher becomes "host is a label-boundary suffix AND (path_prefix == '' OR prefix matches the URL path at a segment boundary)", best row ordered by (host length, then prefix length) — host specificity dominates path specificity, mirroring today's semantics. Segment boundary means /blobby/go/4bd466e8-… matches …/downloads/x.pdf under it but never /blobby/go/4bd466e8-evil…. The recognizer passes parsed.path alongside the host; querystrings never participate.

**Shared-host list**. A declared module (sibling of deliverers.py, same import-validated pure-config discipline): suffix-matched hosts on which a bare registration is forbidden — clean() rejects it with a message naming the maker-attribution problem, and the cite-url funnel rejects minting there. Seed with the RULEBOOK's three: img1.wsimg.com, cdn.shopify.com, storage.googleapis.com.

**Patch verb**. domains: entries may carry a path: img1.wsimg.com/blobby/go/4bd466e8-… (or full-URL form). Parser splits into (host, path_prefix); the silent-drop behavior dies. Flippatch's patch.schema.json description text and patchkit need the matching small touch (separate repo, sequenced after this lands).

**Downstream surfaces**. Admin inline gains the column (root-only surface unchanged). DuckDB citation_root_domains view + citation_root_for_host() macro become path-aware (or explicitly documented as host-only approximation — see questions). docs/Citations.md recognition section updated.

**Unchanged**: scheme recognition, exact child-link match, deliverers, archive: interplay (recognition runs on the live ref URL; the Wayback link rides as a second link — no path logic touches it).

### Open questions

**Is `path_prefix` general or shared-host-only?** (a) Any root may declare a prefix on any host, or (b) prefixes allowed only on declared shared hosts, forbidden elsewhere. I recommend (b) — start tight per the project's validate-strictly rule; relaxing later is a one-line change, and (a) invites path-fragmenting a normal maker site that subdomains/suffix matching already handle.

**Percent-encoding and case in prefixes**. Paths are case-sensitive and the forcing case (a hex UUID segment) has no encoding ambiguity. I recommend verbatim storage and exact segment comparison against urlparse(url).path as-pasted, documented — no decode/normalize pass beyond the trailing-slash/leading-slash chokepoint. A decode layer buys generality no known tenant scheme needs and creates %2F ambiguities.

**Can a bare-host row and prefixed rows coexist on the same (non-shared) host** (longest prefix wins, mirroring subdomain semantics)? Falls out naturally from the matcher; only relevant if you pick 1(a). Under 1(b) it can't arise.

**DuckDB layer**: make citation_root_for_host path-aware now (it would need the URL, not just the host — a signature change for its callers), or leave it host-only with a documented caveat until an analysis needs it? I lean the latter.

**`classify_url` verdict for an unmatched shared-host URL**: plain 422 at cite-url (minimal), or a distinct teaching verdict like the deliverer notice ("this file lives on a shared CDN — register the maker's tenant prefix first")? The deliverer-notice pattern fits, but it's more surface; minimal 422 may do for v1.

Sequencing note: with only the model + matcher + `domains`: verb landed here, the fish-tales patch unblocks — the Cardona family patch declares `domains: ["img1.wsimg.com/blobby/go/4bd466e8-edb0-49f6-afcc-31250ba5b0f3"]` on the `cardonapinball.com` root and its release-notes cites resolve. The funnel/classify work (hazard 2) is separable but I'd keep it in the same change since the shared-host list arrives anyway.
