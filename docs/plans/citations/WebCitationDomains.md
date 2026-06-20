# Plan: citation domain improvements

## Context

Authoring web citations, both via the UI and data patches, has hit some problems:

### Subdomains aren't automatically matched

Pasting (or data-patching) `s4.american-pinball.com/manual.pdf` (one of American Pinball's static asset hosts) isn't recognized as American Pinball, even though `american-pinball.com` is already a seeded root — the author is offered "create a new source" in the UI, and the patch fails to apply.

`recognize_url` matches a pasted URL to a web root only by exact host (modulo `www.`), so `s4.american-pinball.com` ≠ `american-pinball.com` and `get_or_create_web_source` raises at apply time. The workarounds (seed a second root, or add the host as a second `homepage` link) are friction the author has to discover.

### Citation web roots aren't deduped by domain

The catalog accumulates duplicate roots for the same site. In dev _and_ prod, roots **49** `This Week in Pinball (TWiP)` (empty) and **406** `This Week in Pinball` (2 children) both point at `twip.kineticist.com`.

The seeding dedup key is `(name, source_type)`, which never looks at URLs — so two roots with the **same** homepage host but cosmetically different names both get created.

### Child citation sources carry mistyped homepage links

There are **145 `homepage`-typed links on child sources** in dev and prod, though `homepage` is conventionally a root's link.

A seed-ingest bug that created them was fixed in commit `4618b914` (Jun 9), but `create_citation_source` still defaults an omitted `link_type` to `"homepage"`. Under the model below this is **cosmetic** (recognition no longer reads `link_type`), so cleaning it up is non-blocking — but it's still worth tidying.

## Decisions

### Own the recognition host as a fact — `CitationSourceRootDomain`

A new table: `CitationSourceRootDomain(source FK → CitationSource [CASCADE], host CharField **unique**, indexed)`. `host` is the normalized recognition host (www-stripped, lowercased). One root owns many domains (Wikipedia `en`/`de`, a rebrand's old+new domain, a `.com`+`.co.uk`). **Recognition reads this table directly** and never consults `link_type`.

A prior version of this plan derived the recognition signal from `link_type='homepage' AND parent_id IS NULL` on `CitationSourceLink`, which forced a long tail of invariants to keep the projection honest — a computed `match_host` column, a `save()`/`update_fields` staleness fix, a `CheckConstraint`, a `parent__isnull` recognition guard, FK-safety in `clean()`, a "homepage is root-only" rule, and a _blocking_ migration to reclassify the 145 mistyped links before that rule. Modeling the host as an owned fact deletes **all** of that:

- Recognition = an indexed lookup on `CitationSourceRootDomain.host` (longest-suffix). Rows exist only for roots by construction — no `parent` filter, no polymorphism.
- Dedup guarantee = a **plain `unique`** on `host`. No partial-with-condition.
- The 145 child `homepage` links are irrelevant to recognition, so reclassifying them is optional cosmetic cleanup, not a blocking precondition.
- No derived column → no compute-in-`clean()`, no `update_fields` staleness, no `CheckConstraint`, no FK-safety dance.

### Any root with a homepage link gets a recognition domain — not web-only

`CitationSourceRootDomain` attaches to **any** parentless source that has a homepage link, regardless of `source_type`. This preserves current behavior: `recognize_url` step 3 today matches homepage links on any parentless root with **no `source_type` filter**, so books/magazines that carry a homepage link are already URL-recognizable. Backfill (§1.3), the create paths (§1.5b) and the admin inline (§1.6) all stay any-root so the four touchpoints agree. Narrowing recognition to web-only would be a deliberate behavior change with its own audit — out of scope here.

### Homepage links stay — for display, decoupled from recognition

A root keeps its `homepage`-typed `CitationSourceLink` as the human-facing URL (which can be richer than `https://host/`). It is **not** the recognition signal and is **not** derived from / kept in sync with `CitationSourceRootDomain`. The root-domain row is set once at root creation from the homepage host and is thereafter an independent owned fact — so editing a display homepage link never silently changes recognition, and there's no drift to guard against. Changing a recognition host is a deliberate edit of `CitationSourceRootDomain` (admin/gardening), not a side effect.

### Match subdomains, most-specific-wins

For a URL host `H`, the winning root is the one whose `CitationSourceRootDomain.host` is the **longest label-boundary suffix** of `H` (`M == H` or `H.endswith("." + M)`). `s4.american-pinball.com` → `american-pinball.com`; a deliberately-seeded `twip.kineticist.com` still wins over `kineticist.com` for its subtree. Pure string ops over the seeded rows — deterministic, offline, **no PSL** in this path.

### Two PRs

- **PR 1 — the fix (no PSL).** The model, the matcher, the cleanup migration, the dedup. Closes all three Context problems, is mostly read-path, needs no new dependency, and carries little of the risk.
- **PR 2 — governance.** PSL + public-suffix guard, the eTLD+1 contributor restriction, the atomic create-from-URL endpoint, and the cosmetic `link_type` tidy-up. This is the deliberate anti-fragmentation layer and the richer create UX.

## PR 1 — root-domain matching + dedup

Sections are in build order, one commit each, 🛑 STOP for user review before committing. In commit messages, do NOT reference ephemera that future readers will not understand, such as step numbers, PR numbers, links to this plan.

### ✅ DONE: 1.1 Pure helpers — NEW `backend/apps/citation/hosts.py` (model-free, no PSL)

Model-free module so `models`, `extractors`, `seeding` and migrations can import it without a cycle. All take a **host**, not a URL — callers parse `urlparse(url).hostname` first (None → skip).

- `normalize_host(hostname) -> str` (www-strip + lower; replaces `extractors._normalize_domain`).
- `label_suffixes(host) -> list[str]` → `["s4.american-pinball.com", "american-pinball.com", "com"]`.
- `class RootDomainMatch(NamedTuple)` (`source_id`, `source_name`, `host`).
- `longest_suffix_match(url_host: str, domains: Sequence[RootDomainMatch]) -> RootDomainMatch | None` — longest label-boundary suffix wins; ties impossible (host unique). **Pure.**
- **Tests (write first, no DB)**, parametrized like `TestYouTubeNormalize`: s4→registrable, twip-wins-over-kineticist, `www` both sides, `evil-american-pinball.com` non-match, deeper sub-subdomain → nearest, empty host; `normalize_host`; `label_suffixes`.

🛑 STOP for user review before committing.

### 1.2 Model — `backend/apps/citation/models.py`

This is the model class **plus its generated `CreateModel` migration** (the `host` `unique` lands here, on an empty table — low-risk schema-only; the destructive data step is the separate §1.3 commit).

- `CitationSourceRootDomain`: `source = FK(CitationSource, on_delete=CASCADE, related_name="root_domains")` (a domain is wholly owned by its root); `host = CharField(max_length=253, unique=True)`, `field_not_blank("host")`. `host` is stored **normalized** (lowercased, `www.`-stripped) — every write goes through `normalize_host`, which is what makes the `unique` meaningful. No `db_index=True` (`unique=True` already creates the index — a second is redundant). Use a named constant for the 253 max (the DNS hostname limit). No `match_host` on `CitationSourceLink`, no derived-field machinery.
- **Root-only, enforced in `clean()`.** A `CheckConstraint` can't reach `source.parent_id` across the FK, so the invariant lives in `CitationSourceRootDomain.clean()`: **reject a row whose `source` has a parent** (a domain may attach only to a root). This guards every `full_clean` path — notably the §1.6 admin inline, where a curator could otherwise attach a domain to a _child_ and squat its globally-`unique` host, blocking the real root from ever claiming it (recognition would ignore the row via the filter below, but the host would still be taken). Recognition also keeps a cheap defensive `source__parent__isnull=True` filter (§1.4) for rows that bypass `clean()` (raw SQL / bulk). State the invariant in the model docstring.
- No new `CitationSourceLink` constraints/rules in PR 1. `homepage` links are untouched (display only).

🛑 STOP for user review before committing.

### 1.3 Data migration — `backend/apps/citation/migrations/`

The only prod-data surgery in the plan (deletes a root, backfills recognition rows).

- `RunPython`: **delete root 49** (assert name `This Week in Pinball (TWiP)` + homepage `twip.kineticist.com` + **zero children AND zero `instances`** before delete — `CitationInstance.citation_source` is `PROTECT` ([provenance citation_instance.py:116]), so a stray instance would block the delete with an opaque error; dev is clean, prod must be asserted).
- **Reverse restores the pre-migration state fully.** Forward both deletes root 49 **and** inserts `CitationSourceRootDomain` rows; the table was empty before this migration, so the reverse must **delete all `CitationSourceRootDomain` rows** _and_ recreate root 49. A reverse that only recreates root 49 leaves the backfilled rows behind, so reverse-then-reapply trips the `host` `unique`.
- **Audit before inserting.** Build the `{normalized host: [roots]}` map across all roots' homepage links in memory first; if any host is owned by >1 root (beyond the handled TWIP pair), **raise listing the colliding roots** — _before_ any insert. Otherwise the offending `INSERT` mid-loop trips the `host` `unique` and surfaces an opaque `IntegrityError` instead of the helpful message. Then insert one root-domain per host. Inline the normalization (`urlparse(url).hostname`, strip `www.`, lower) rather than importing `hosts.py`, so the frozen migration stays self-contained (matches `provenance/0004`, which imports no app code). Child homepage links are skipped (not roots), as is any link whose `urlparse(...).hostname` is `None`.
- **Tests (after — test-first is awkward for migrations):** backfill creates a row per root homepage host, skips children, deletes root 49; the audit raises on an unexpected duplicate host.

Review the migration + dry-run output.

🛑 STOP for user review before committing.

### 1.4 Recognition — `backend/apps/citation/extractors.py`

- Rewrite step 3 of `recognize_url`: parse `urlparse(url).hostname` (None → no match) → `normalize_host`; query `CitationSourceRootDomain.objects.filter(host__in=label_suffixes(host), source__parent__isnull=True).select_related("source")`; pick the longest host; return its source. The `parent__isnull` filter is cheap defense-in-depth for the app-only root-only invariant (§1.2). Replaces the full-table Python loop over homepage links. Steps 1 (extractor) and 2 (exact child link) unchanged. The `host__in` filter already restricts candidates to exact label-boundary suffixes, so "pick longest" is just max-by-length — reuse §1.1's `longest_suffix_match` over the fetched rows (keeps selection logic unit-tested) rather than re-deriving it inline.
- **Rewrite the recognition docs in this commit, not PR 2.** Recognition behavior changes _here_, so its docs change here. Rewrite the `recognize_url` docstring — the current working-tree edit at [extractors.py:128-138] argues _against_ subdomain loosening and is now superseded — and `docs/Citations.md`'s step-3 + homepage-link explanation, to describe `CitationSourceRootDomain` as the recognition signal and the longest-suffix subdomain match. PR 2's §2.6 keeps only the PSL/eTLD+1 doc additions.
- **Tests:** `s4.american-pinball.com/…` → American Pinball; `twip.kineticist.com/…` → the TWIP root (most specific) when one exists, else the Kineticist root; a deeper subdomain → nearest root.

🛑 STOP for user review before committing.

### 1.5a Seeding typing cleanup (prep, no behavior change) — `backend/apps/citation/seeding.py`

Pure refactor, landed _before_ §1.5b so the host-dedup commit is behavior-only and reviewable in isolation. Make `_lookup_source`'s return a `NamedTuple` and replace the `dict[str, object]` field-bags (`_source_fields`/`_create_source`) with a `str | int | None` alias, lifting `parent` to a typed param. No functional change; the existing seeding tests stay green.

🛑 STOP for user review before committing.

### 1.5b Creation + seeding dedup — `backend/apps/citation/{api.py,seeding.py}`

Creation and dedup ship together: without dedup, re-seeding a root under a cosmetically different name would create a second root and trip the `host` `unique` (an `IntegrityError` that wedges the patch queue).

- **Root creation makes a root-domain row — any-root, not web-only.** Wherever a parentless source is created with a homepage link — `ensure_root_source` (patch `sources:`) and `create_citation_source` (parent-less) — also create `CitationSourceRootDomain(host=normalize_host(urlparse(homepage_url).hostname))`, regardless of `source_type` (matching the §1.3 backfill and current recognition; see the any-root decision). Skip when `hostname` is `None` — `URLField` makes that near-impossible, but honor §1.1's None→skip contract. **full_clean the row** (the `_clean_and_save` pattern, not a raw `.create()`) so §1.2's root-only `clean()` and §2.2's public-suffix `clean()` actually fire. The homepage link is still created (display). Children get none.
- **Additive multi-domain seeding.** `ensure_root_source` is additive: when a patch adds a **new** homepage host to an existing root, mint a `CitationSourceRootDomain` per new host too (one row per distinct host, mirroring §1.3's backfill). This builds the "one root owns many domains" shape (rebrand, `.com`+`.co.uk`) incrementally.
- **Seeding dedup by host.** In `_lookup_source` (or a helper), resolve **all** the node's declared homepage hosts to existing roots via `CitationSourceRootDomain.host`, then in order: **>1 distinct root** (declared hosts already owned by different roots) → **warn and skip the node, no writes** (don't pick one and then trip the `host` `unique` minting the other — that wedges the queue); **exactly 1 root** → that's the match; **0 roots** → **fall back to the `(name, source_type)` root lookup** — a same-named root simply gaining a _new_ homepage host must be found, not duplicated — and only **create** if that misses too. Then on the matched-or-created root, **additively** mint a `CitationSourceRootDomain` for each declared host it doesn't already own. Resolve the multi-root case up front, before any write. (Builds on the §1.5a typing cleanup.)
- **Tests:** creation makes a row (API + patch); a patch re-declaring an existing root **by name** with a new homepage host finds it via `(name, source_type)` and adds the domain — **no duplicate root**; dedup-by-host (re-seed TWIP under a new name → finds the existing root by host, no new row, warns); a node whose declared hosts span two existing roots warns and skips with no writes (not an `IntegrityError`); the `unique` rejects a second root claiming the same host.

🛑 STOP for user review before committing.

### 1.6 Admin inline — `backend/apps/citation/admin.py`

- V1 computed the recognition signal in `save()`, so an admin-created root recognized for free; V2 needs the row inserted explicitly, and admin is a creation path. Add a `CitationSourceRootDomain` `TabularInline` on the `CitationSource` admin so a curator manages domains alongside the root. **Not** a `save()` hook that auto-derives the row from the homepage link — that re-introduces exactly the link→recognition coupling (and drift) V2 exists to remove; domains stay explicitly owned.
- The inline relies on §1.2's `clean()` root-only rule: adding a domain to a **child** source is rejected at form validation (a child can't squat a host the real root needs), so no inline-specific gating is required beyond surfacing that `ValidationError`.
- **Tests:** thin (admin) — a root + domain creates through the admin form; adding a domain to a child source is rejected.

🛑 STOP for user review before committing.

### 1.7 Exact-link-matches-root fix (bug → failing-test-first) — `backend/apps/citation/extractors.py`

- `get_or_create_web_source`'s pre-recognition exact-link reuse ([extractors.py:316]) matches any link by URL, so citing a URL equal to a root's homepage (`https://american-pinball.com/`) returns the abstract root, not a child. Filter that lookup to `citation_source__parent__isnull=False` (children only), then fall through to recognition's domain match → create/reuse a child. (`recognize_url`'s own exact-link step already filters to children, [extractors.py:179].) Independent of the root-domain work — it fixes the existing patch path.
- **Tests (failing-first):** citing a URL equal to an existing root homepage creates/reuses a **child**, not the root.

🛑 STOP for user review before committing.

## PR 2 — governance (PSL + eTLD+1 + atomic create endpoint)

Sections are in build order, one commit each, 🛑 STOP for user review before committing. In commit messages, do NOT reference ephemera that future readers will not understand, such as step numbers, PR numbers, links to this plan.

### 2.1 Public Suffix List

- Add `publicsuffixlist` (bundled snapshot, no network) to `backend/pyproject.toml`. Add `is_public_suffix(host) -> bool` and `registrable_domain(host) -> str | None` to `hosts.py` — the single `Any` boundary for the untyped dep (`ignore_missing_imports` in `[tool.mypy]`, no scattered `# type: ignore`). Pure (table lookup). Used only at write/validate time, never in recognition, so matching stays PSL-free and deterministic.
- **We don't maintain a local denylist.** The PSL (its PRIVATE section) already is the infrastructure-host list (`cloudfront.net`, `s3.amazonaws.com`, `github.io`, …); gaps go upstream, not into a forked copy.

🛑 STOP for user review before committing.

### 2.2 Public-suffix guard (model-level)

- `CitationSourceRootDomain.clean()` rejects a `host` that `is_public_suffix` — a bare `cloudfront.net` / `co.uk` can't be a recognition host, on every path (API, patch, admin). A real invariant on a dedicated model (no link polymorphism to dance around).
- **Audit existing rows when this lands.** PR 1 ships with no PSL guard, so a bad host could already sit in `CitationSourceRootDomain` (and silently drive recognition) by the time PR 2 deploys — `clean()` only blocks _new_ writes. Ship a data migration alongside the guard that scans existing `host`s for public suffixes and **raises listing any offenders** (don't auto-delete — a row may have children routing to it; a human resolves), so deploy fails loud rather than leaving a live vacuum root.
- **Tests:** `com`/`co.uk`/`github.io` rejected on write; `american-pinball.com` accepted; the audit migration raises on a pre-existing public-suffix row.

🛑 STOP for user review before committing.

### 2.3 eTLD+1 contributor restriction — `api.py`

- **Guards exactly one contributor path: the recognition host minted by §1.5b's `create_citation_source` branch for a parentless root.** Reject a host that isn't its own eTLD+1 (`registrable_domain(host)`), with an error naming the registrable domain. Keyed on **a `CitationSourceRootDomain` being minted, not on `source_type`** — root-domains are any-root (Decisions), so a contributor making a non-web root with a subdomain homepage host must be guarded too; the anti-fragmentation rule is about the recognition host, not the medium. That mint is the only place a contributor sets a recognition host:
  - `cite-url` (§2.4) auto-roots at the registrable domain by construction, so it needs no check.
  - There is **no contributor edit-recognition-host endpoint** — admin owns recognition-host edits via the §1.6 inline. (No "update path" / "merged effective host" machinery — that was V1-era, from when recognition _was_ the homepage link.)
  - `update_citation_source_link` is **not** guarded: the homepage `CitationSourceLink` is decoupled from recognition (Decisions), so its host no longer affects matching — policing it would be pointless.
- Patches are exempt (trusted) — they may seed subdomain roots (`twip.kineticist.com`).
- **Tests:** `create_citation_source` for a parentless root rejects a subdomain host (message points at the registrable domain) and accepts the registrable domain; the same rejection fires for a non-web root (any-root coverage); a patch may create a subdomain root.

🛑 STOP for user review before committing.

### 2.4 Atomic "cite a web URL" endpoint — `api.py`

- `POST /api/citation-sources/cite-url/`, `@requires(Activity.CITATION_EDIT)`, no throttle (recognition is local DB). **Request** carries the reviewed draft `{url, name, publisher, author, year}` (fields `extract_url` scrapes / the user edits, [url_extraction.py:180-187]); `source_type` is implied `web`; `name`/`author`/`year` apply to the **child**, `publisher` to the **root**. **Response** is the child to cite (`id`, `name`, `skip_locator`). One transaction, attributing every created row to `request.user`:
  1. `recognize_url(url)` returns one of four shapes — handle all for direct-API robustness (the frontend pre-routes, but the contract shouldn't be silent): **exact child** → reuse; **scheme identifier, no child yet** (`identifier` set, `child=None` — a pasted IPDB/OPDB URL) → **422**, telling the caller to use the `scheme:identifier` path. (Not routed through `get_or_create_external_source` — that patch helper writes no `created_by`/`updated_by`, which would break this endpoint's every-row-attributed promise; the frontend pre-routes scheme URLs anyway.); **domain match** → child under the root; **no match** → `registrable_domain(host)` → **422 if `None`** (bare public suffix) → else get-or-create the **root** (+ its `CitationSourceRootDomain` at the registrable domain, **full_cleaned** so the model guards fire; homepage link `https://{registrable_domain}/` — `CitationSourceLink.url` is a `URLField`, a bare host fails validation; root `name` = `publisher` if given else the registrable domain) and create the child.
  2. **Root-create race:** the create-root branch runs inside a **savepoint** (nested `atomic`). If a concurrent request trips the `host` `unique`, the `IntegrityError` poisons only the savepoint — roll it back, then re-run `recognize_url` (the root now exists) and nest the child. (A bare `except IntegrityError` without the savepoint can't re-query — the outer transaction is poisoned.)
  3. **Same-URL child race (accepted):** two concurrent cites of the same URL under an existing root can both create a child (no `unique` spans child reference URLs — distinct child `citation_source`s). Unlike the root race this raises nothing, so it's left as a benign rare duplicate for gardening to merge, not handled inline. Call it out so it's a decision, not an oversight.
- **Scope:** this is _only_ the URL-paste, no-explicit-parent path. When the user picked a `parentContext`, the child create stays on `create_citation_source` with that `parent_id` — recognition must never override a deliberate parent choice (else `twip.kineticist.com` pasted under a hand-picked "Kineticist" would silently reroute).
- Keeps PSL/eTLD+1/root-host logic backend-side; the frontend POSTs the draft and cites the returned child. `get_or_create_web_source` (patch path) stays lean and raises on no root — interactive root creation lives here, not there.
- **Tests:** child reuse; a scheme URL → 422 (use `scheme:identifier`); domain-match nest; no-match creates root (+ root-domain + child) named from `publisher`, all rows attributed; bare-public-suffix → 422; the root-create race re-recognizes and nests (savepoint) instead of 500ing; an explicit `parentContext` does not reroute.

Run `make codegen`.

🛑 STOP for user review before committing.

### 2.5 Frontend — `frontend/src/lib/components/input/citation/`

- **Surface the recognized parent on a domain match.** `CitationSearchStage.svelte`'s `create_by_url` item carries `parentName` but renders only the URL + "Create & cite" ([:148-154], [:390-407]) — a domain match looks identical to a brand-new source (the `twip.kineticist.com` screenshot). Render "Create a page under **This Week in Pinball**."
- **Create-from-URL POSTs the reviewed draft to §2.4 and cites the returned child.** The user still reviews/edits the name; the draft rides along, so the metadata isn't discarded. No PSL, no host munging, no two-call partial-failure in Svelte. The cited record is the web **child** (`skip_locator=true`), not the abstract root. Only the no-explicit-parent path reroutes here.
- **Tests:** dom test — a domain match renders the parent name; create-from-URL sends the draft and cites the returned child.

🛑 STOP for user review before committing.

### 2.6 Cosmetic `link_type` tidy-up (non-blocking)

- Now that recognition ignores `link_type`, the 145 child `homepage` links are purely a display wart. Reclassify them → `reference` (one-off migration) and fix the default footgun: change the create schema's `link_type` default from `"homepage"` to `None` ([schemas.py:207-210]) AND make `create_citation_source` parent-aware (`data.link_type or ("homepage" if parent is None else "reference")`) — the schema default currently shadows the `or`. Optional; bundle with PR 2 or split out.
- **Docs:** add the PSL / public-suffix-guard / eTLD+1 governance docs to `docs/Citations.md`. (The `recognize_url` docstring, `CitationSource` docstring and `docs/Citations.md` step-3 / homepage-link rewrites land in §1.4, where recognition behavior actually changes — not here.)

🛑 STOP for user review before committing.

## Verification

```bash
cd backend && uv run pytest apps/citation -q
uv run python manage.py migrate
uv run python manage.py shell -c "from apps.citation.extractors import recognize_url; print(recognize_url('http://s4.american-pinball.com/games/gtf/docs/manual.pdf'))"
# → Recognition(parent_name='American Pinball', ...)
uv run python manage.py shell -c "from apps.citation.models import CitationSource as C; print(C.objects.filter(parent__isnull=True, name__icontains='week in pinball').count())"
# → 1   (root 49 gone)
make mypy && make lint
```

Prod: the PR 1 migration removes root 49 and backfills root-domains on deploy.

## Known limitations

- **Asset hosts on a different registrable domain** (a third-party CDN like `…cloudfront.net`, or any host not under the publisher's domain) won't match — longest-suffix only collapses within one registrable domain. These need an extra `CitationSourceRootDomain` row on the root (a deliberate alias) or a separate root.
- **Non-PSL "subdomain-per-publisher" platforms** collapse to one shared registrable-domain root under the eTLD+1 rule until an admin gardens them apart.

## Deferred

- **Admin "promote a subdomain into its own root" gardening tool** — creates a more-specific root and reparents the children that now route to it (an explicit, visible move, trusted-only). The single home for reparenting. Until then, creating a more-specific root leaves existing children under the ancestor (a temporary split); a child's parent is set at cite time and not retroactively maintained.

## Never'ed

- **Delete + reparent** — a source with children must never be deletable; `on_delete=PROTECT` on the parent FK enforces it. No code reparents on delete.
- **Auto-reparent on save** — rejected; it bred `save()`-side-effect complexity. Regrouping is deliberate gardening.
- **Fold TWIP into Kineticist** — keep root 406 as its own publication.
