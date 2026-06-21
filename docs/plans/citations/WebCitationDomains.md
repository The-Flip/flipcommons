# Plan: citation domain improvements

> **Superseded.** The write-layer cleanup is now planned in [CitationsCleanup.md](CitationsCleanup.md); the domain-governance work (subdomain matching, the PSL public-suffix guard, rounding, `domains:`) in [CitationDomainGovernance.md](CitationDomainGovernance.md). This file and its intermediate successor [WebCitationDomains2.md](WebCitationDomains2.md) are kept only as history — the DONE sections record what's built on the branch. Work from the two current plans.

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
- **PR 2 — governance.** PSL + public-suffix guard + registrable-domain rounding of minted recognition hosts. This is the deliberate anti-fragmentation layer. (The `link_type` tidy-up split out into its own `Cleanup` section — it has nothing to do with governance.)

## ✅ DONE: PR 1 — root-domain matching + dedup

Sections are in build order, one commit each, 🛑 STOP for user review before committing. In commit messages, do NOT reference ephemera that future readers will not understand, such as step numbers, PR numbers, links to this plan.

### ✅ DONE: 1.1 Pure helpers — NEW `backend/apps/citation/hosts.py` (model-free, no PSL)

Model-free module so `models`, `extractors`, `seeding` and migrations can import it without a cycle. All take a **host**, not a URL — callers parse `urlparse(url).hostname` first (None → skip).

- `normalize_host(hostname) -> str` (www-strip + lower; replaces `extractors._normalize_domain`).
- `label_suffixes(host) -> list[str]` → `["s4.american-pinball.com", "american-pinball.com", "com"]`.
- `class RootDomainMatch(NamedTuple)` (`source_id`, `source_name`, `host`).
- `longest_suffix_match(url_host: str, domains: Sequence[RootDomainMatch]) -> RootDomainMatch | None` — longest label-boundary suffix wins; ties impossible (host unique). **Pure.**
- **Tests (write first, no DB)**, parametrized like `TestYouTubeNormalize`: s4→registrable, twip-wins-over-kineticist, `www` both sides, `evil-american-pinball.com` non-match, deeper sub-subdomain → nearest, empty host; `normalize_host`; `label_suffixes`.

🛑 STOP for user review before committing.

### ✅ DONE: 1.2 Model — `backend/apps/citation/models.py`

This is the model class **plus its generated `CreateModel` migration** (the `host` `unique` lands here, on an empty table — low-risk schema-only; the destructive data step is the separate §1.3 commit).

- `CitationSourceRootDomain`: `source = FK(CitationSource, on_delete=CASCADE, related_name="root_domains")` (a domain is wholly owned by its root); `host = CharField(max_length=253, unique=True)`, `field_not_blank("host")`. `host` is stored **normalized** (lowercased, `www.`-stripped) — every write goes through `normalize_host`, which is what makes the `unique` meaningful. No `db_index=True` (`unique=True` already creates the index — a second is redundant). Use a named constant for the 253 max (the DNS hostname limit). No `match_host` on `CitationSourceLink`, no derived-field machinery.
- **Root-only, enforced in `clean()`.** A `CheckConstraint` can't reach `source.parent_id` across the FK, so the invariant lives in `CitationSourceRootDomain.clean()`: **reject a row whose `source` has a parent** (a domain may attach only to a root). This guards every `full_clean` path — notably the §1.6 admin inline, where a curator could otherwise attach a domain to a _child_ and squat its globally-`unique` host, blocking the real root from ever claiming it (recognition would ignore the row via the filter below, but the host would still be taken). Recognition also keeps a cheap defensive `source__parent__isnull=True` filter (§1.4) for rows that bypass `clean()` (raw SQL / bulk). State the invariant in the model docstring.
- No new `CitationSourceLink` constraints/rules in PR 1. `homepage` links are untouched (display only).

🛑 STOP for user review before committing.

### ✅ DONE: 1.3 Backfill migration — `backend/apps/citation/migrations/`

Backfill recognition rows from existing homepage links. The duplicate-root delete is **manual** (see below), not migration logic — keeping it out of the migration removes the fingerprint matching, `ProtectedError`/provenance coupling, the reverse-recreate-root logic and the pk-drift round-trip bug that an in-migration delete dragged in.

- **Manual one-off prod cleanup (not in the migration): delete root 49.** The empty duplicate `This Week in Pinball (TWiP)` collides with the populated `This Week in Pinball` on `twip.kineticist.com`. Delete it by hand in a prod shell, guarded with `assert r.name == "This Week in Pinball (TWiP)" and not r.children.exists() and not r.instances.exists()` before `r.delete()`. Run this **before** the backfill migration deploys — otherwise the audit (below) trips on the twip collision. Dev is already clean; CI/fresh DBs never had it.
- **`RunPython` backfill (any-root).** Build the `{normalized host: {roots}}` map across all roots' homepage links (no `source_type` filter — the any-root decision). Inline the normalization (`urlparse(url).hostname`, strip trailing dot, `www.`, lower) rather than importing `hosts.py`, so the frozen migration stays self-contained (matches `provenance/0004`). Child homepage links are skipped (not roots), as is any link whose hostname is `None`. The same root declaring a host twice (http+https) is fine; two different roots is not.
- **Audit before inserting.** If any host is owned by >1 root, **raise listing the colliding roots** before any insert — this is the safety net if the manual root-49 delete was skipped. Otherwise the `INSERT` mid-loop trips the `host` `unique` with an opaque `IntegrityError`.
- **Reverse just empties the table.** The table was empty before this migration, so reverse deletes all rows — restoring the pre-migration state and keeping reverse-then-reapply clean (no root recreation; the manual delete is not migration-owned).
- **Tests (after — test-first is awkward for migrations):** backfill creates a row per root homepage host; backfills any root type (web/book/magazine — locks in any-root); skips children; same-root-twice is not a collision; the audit raises on a host owned by two roots; reverse empties the table; reverse-then-reapply rebuilds rows.

Review the migration + dry-run output.

🛑 STOP for user review before committing.

### ✅ DONE: 1.4 Recognition — `backend/apps/citation/extractors.py` (committed with §1.5a/§1.5b)

- Rewrite step 3 of `recognize_url`: parse `urlparse(url).hostname` (None → no match) → `normalize_host`; query `CitationSourceRootDomain.objects.filter(host__in=label_suffixes(host), source__parent__isnull=True).select_related("source")`; pick the longest host; return its source. The `parent__isnull` filter is cheap defense-in-depth for the app-only root-only invariant (§1.2). Replaces the full-table Python loop over homepage links. Steps 1 (extractor) and 2 (exact child link) unchanged. The `host__in` filter already restricts candidates to exact label-boundary suffixes, so "pick longest" is just max-by-length — reuse §1.1's `longest_suffix_match` over the fetched rows (keeps selection logic unit-tested) rather than re-deriving it inline.
- **Rewrite the recognition docs in this commit, not PR 2.** Recognition behavior changes _here_, so its docs change here. Rewrite the `recognize_url` docstring — the current working-tree edit at [extractors.py:128-138] argues _against_ subdomain loosening and is now superseded — and `docs/Citations.md`'s step-3 + homepage-link explanation, to describe `CitationSourceRootDomain` as the recognition signal and the longest-suffix subdomain match. PR 2's §2.3 keeps only the PSL/registrable-domain doc additions.
- **Tests:** `s4.american-pinball.com/…` → American Pinball; `twip.kineticist.com/…` → the TWIP root (most specific) when one exists, else the Kineticist root; a deeper subdomain → nearest root.

🛑 STOP for user review before committing.

### ✅ DONE: 1.5a Seeding typing cleanup (prep, no behavior change) — `backend/apps/citation/seeding.py`

Pure refactor, landed _before_ §1.5b so the host-dedup commit is behavior-only and reviewable in isolation. Make `_lookup_source`'s return a `NamedTuple` and replace the `dict[str, object]` field-bags (`_source_fields`/`_create_source`) with a `str | int | None` alias, lifting `parent` to a typed param. No functional change; the existing seeding tests stay green. (§1.5b reshapes this resolver — it must also consider hosts and distinguish matched-by-host from matched-by-name — so the `NamedTuple`'s fields will likely widen there; that's fine, 1.5a just tightens the existing shapes.)

🛑 STOP for user review before committing.

### ✅ DONE: 1.5b Creation + seeding dedup — `backend/apps/citation/{api.py,seeding.py}`

Creation and dedup ship together: without dedup, re-seeding a root under a cosmetically different name would create a second root and trip the `host` `unique` (an `IntegrityError` that wedges the patch queue).

- **Homepage-typed links only.** Throughout this section, "declared homepage host(s)" means the hosts of a node's `link_type='homepage'` links (matching the §1.3 backfill and the create paths) — non-homepage links (`catalog`/`reference`/…) contribute no recognition host. For `create_citation_source` the homepage link is the single attached `url` when `(data.link_type or "homepage") == "homepage"`.
- **Root creation makes a root-domain row — any-root, not web-only.** Wherever a parentless source is created with a homepage link — `ensure_root_source` (patch `sources:`) and `create_citation_source` (parent-less, homepage link) — also create `CitationSourceRootDomain(host=normalize_host(urlparse(homepage_url).hostname))`, regardless of `source_type` (matching the §1.3 backfill and current recognition; see the any-root decision). Skip when `hostname` is `None` — `URLField` makes that near-impossible, but honor §1.1's None→skip contract. **full_clean the row** (the `_clean_and_save` pattern, not a raw `.create()`) so §1.2's root-only `clean()` and §2.2's public-suffix `clean()` actually fire. Mint after the source/link exist, inside the **existing** `transaction.atomic` — no savepoint (an `IntegrityError` exits the block and rolls back; the savepoint dance is §1.1a's concern). The homepage link is still created (display). Children get none.
- **API path mints but does not dedup.** `create_citation_source` only mints; it does **not** run the host-dedup below (that's seeding-only; the interactive create-from-URL dedup is §1.1a). A user creating a root whose host another root already owns therefore hits the `host` `unique` — surface it as a friendly **422** via `_clean_and_save`'s `integrity_msg` ("That domain is already recognized by another source"), not the raw DB message.
- **Additive multi-domain seeding.** `ensure_root_source` is additive: when a patch adds a **new** homepage host to an existing root, mint a `CitationSourceRootDomain` per new host too (one row per distinct host, mirroring §1.3's backfill). This builds the "one root owns many domains" shape (rebrand, `.com`+`.co.uk`) incrementally.
- **Seeding dedup by host — exact host, not suffix.** In `_lookup_source` (or a helper that takes the `node`/its declared homepage hosts, not just `fields`), resolve **all** the node's declared homepage hosts to existing roots via **exact** `CitationSourceRootDomain.host == h` equality — **never** the longest-suffix matcher. Recognition (§1.4) is suffix-based; dedup must not be, or deliberately seeding a more-specific subdomain root (`twip.kineticist.com` under an existing `kineticist.com`) would resolve to the parent domain and never get its own root, contradicting most-specific-wins and the deferred promote-subdomain tool. Then in order: **>1 distinct root** (declared hosts already owned by different roots) → **warn and skip the node, no writes** (don't pick one and then trip the `host` `unique` minting the other — that wedges the queue); **exactly 1 root** → that's the match (host wins even if a _different_ root shares the `(name, source_type)` — that's the re-seed-under-a-new-name case); **0 roots** → **fall back to the `(name, source_type)` root lookup** — a same-named root simply gaining a _new_ homepage host (whose exact host isn't seeded yet) must be found, not duplicated — and only **create** if that misses too. Then on the matched-or-created root, **additively** mint a `CitationSourceRootDomain` for each declared host it doesn't already own. Resolve the multi-root case up front, before any write. (Builds on the §1.5a typing cleanup.)
- **Tests:** creation makes a row (API + patch); a patch re-declaring an existing root **by name** with a new homepage host finds it via `(name, source_type)` and adds the domain — **no duplicate root**; dedup-by-host (re-seed TWIP under a new name → finds the existing root by host, no new row, warns); a node whose declared hosts span two existing roots warns and skips with no writes (not an `IntegrityError`); the `unique` rejects a second root claiming the same host.

🛑 STOP for user review before committing.

### ✅ DONE: 1.6 Admin inline — `backend/apps/citation/admin.py`

- V1 computed the recognition signal in `save()`, so an admin-created root recognized for free; V2 needs the row inserted explicitly, and admin is a creation path. Add a `CitationSourceRootDomain` `TabularInline` on the `CitationSource` admin so a curator manages domains alongside the root. This is also the **sole edit path for recognition hosts** — §2.3 deliberately ships no contributor endpoint for it — so it doubles as the gardening surface for alias domains (rebrand old+new, `.com`+`.co.uk`, the deliberate asset-subdomain alias of the known-limitation escape hatch). **Not** a `save()` hook that auto-derives the row from the homepage link — that re-introduces exactly the link→recognition coupling (and drift) V2 exists to remove; domains stay explicitly owned.
- **Show the inline on roots only.** A domain may attach only to a parentless source, so the inline is a trap on a child page — anything entered there only errors. Override `get_inline_instances` to include the root-domain inline only when `obj is None` (the add form) or `obj.parent_id is None`. The `CitationSourceLinkInline` stays on every page.
- **Root-only is enforced by §1.2's `clean()`, but only when `source_id` is populated.** In a Django inline, the parent FK is set at clean time only if the parent already has a pk — so editing an **existing** child and adding a domain is rejected (`source_id` set → `clean()` fires), but creating a **new** child _and_ an inline domain in one add-form skips the check (`source_id is None`). That corner squats a globally-`unique` host on a child; recognition's `source__parent__isnull=True` filter keeps the bad row from driving matches, and admins are trusted, so we **accept** it rather than add formset-level gating. Test the root-only rejection at the **model `clean()` level** (an existing child), not through the admin add form (which the visibility rule already keeps off child pages).
- **No attribution work for the inline.** `CitationSourceRootDomain` extends `TimeStampedModel` only (auto timestamps, no `created_by`/`updated_by`), so the existing `save_formset`'s generic `instance.save()` + `deleted_objects` loop already handles it; the `isinstance(..., CitationSourceLink)` branch correctly skips attribution for it. Loosen `save_formset`'s type annotation, which is currently pinned to the link formset (it's now called per-formset).
- **Tests:** thin — a root + domain creates through the admin form; the root-domain inline is absent on a child source's admin page; `CitationSourceRootDomain.clean()` rejects a domain whose `source` has a parent.

🛑 STOP for user review before committing.

### ✅ DONE: 1.7 Exact-link-matches-root fix (bug → failing-test-first) — `backend/apps/citation/extractors.py`

- `get_or_create_web_source`'s pre-recognition exact-link reuse ([extractors.py:316]) matches any link by URL, so citing a URL equal to a root's homepage (`https://american-pinball.com/`) returns the abstract root, not a child. Filter that lookup to `citation_source__parent__isnull=False` (children only), then fall through to recognition's domain match → create/reuse a child. (`recognize_url`'s own exact-link step already filters to children, [extractors.py:179].) Independent of the root-domain work — it fixes the existing patch path.
- **Tests (failing-first):** citing a URL equal to an existing root homepage creates/reuses a **child**, not the root.

🛑 STOP for user review before committing.

### ✅ DONE: 1.8: Surface the recognized parent on a domain match

On the frontend, surface the recognized parent on a domain match.`CitationSearchStage.svelte`'s `create_by_url` item carries `parentName` but renders only the URL + "Create & cite" ([:148-154], [:390-407]) — a domain match looks identical to a brand-new source (the `twip.kineticist.com` screenshot). Render "Create a page under **This Week in Pinball**."

## ✅ DONE: PR 1.1 — describe-site stage + deferred-write web create

The interactive web-create flow should have two properties that don't depend on the PSL, so they land here ahead of PR 2:

- **Writes happen only on finalize** — nothing is created until the contributor commits the citation, so an abandoned flow leaves no half-described root.
- **A pasted web URL cites a page child** under its site root, never the bare root — upholding `is_abstract`'s contract that the cited record is always a child under the matched root.

PR 1.1 delivers both: a `cite-url` endpoint that creates the site root and the page child, and a "describe this new site" stage. It needs no new dependency — `cite-url` roots at the **raw** host here, and §2.3 rounds it to the registrable domain once the PSL lands.

**Scope: the new-web-root path only** — a pasted web URL whose domain no root yet owns. A domain _match_ recognized at search uses the "Cite a page under **X**" → `create_by_url` path (it writes only on the click); book/magazine and explicit-parent creates use `create_citation_source` (a book root is concrete and citable — no describe-site step). §1.1c unifies the domain-match path onto `cite-url`.

### Decisions

- **Site name** = scraped `og:site_name` (the extract draft's existing `publisher` field) when present, else the **domain**. The fallback-to-domain lives on the backend (root `name = site_name or host`), so the Site field can prefill with `og:site_name` or sit blank and still produce a sensible root name.
- **No description scrape.** `og:description` is page-level, not site-level, so it isn't used. The Site description is an **optional, manual** field — blank by default. (Nothing new to scrape, so the extract draft and its cache key are untouched.)
- **No Author/Year anywhere in the web flow** — neither the describe-site step (site-level) nor the page step (Page name + URL only). A web citation is a site plus a page; Author and Year belong to authored, dated works (books, magazines).
- **Raw host now, registrable domain in §2.3.** PR 1.1 roots a new source at the **raw pasted host** (`normalize_host`); §2.3 rounds that to `registrable_domain` once the PSL lands. A brand-new **subdomain** paste (`blog.newsite.com`, `newsite.com` not yet seeded) therefore roots at the subdomain until §2.3 rounds it; both land in the same branch, so the un-rounded form never reaches prod.

Sections are in build order, one commit each, 🛑 STOP for user review before committing.

### ✅ DONE: PR 1.1a — `cite-url` endpoint (raw host, no PSL) — `api.py`

- `POST /api/citation-sources/cite-url/`, `@requires(Activity.CITATION_EDIT)`, `response={201: CitationSourceMatchSchema, 422: ErrorDetailSchema}` (return `201` always — the exact-child reuse is rare/defensive, not worth a 200/201 split). **Request** `{url, site_name, site_description, page_name}`, every field typed (strong-typing rule): `url: LinkUrlStr` (length-bounded, same as the create schema — it does **not** validate URL shape at the Pydantic boundary), `site_name: NameStr`, `site_description: DescriptionStr`, `page_name: NameStr`. A hostless / `mailto:` URL 422s via the explicit `urlparse(url).hostname is None` guard in the new-root path (before any write); a malformed-but-hosted URL 422s via the child/homepage link's model-level `URLField` through `_clean_and_save`. No new write paths bypass these. **Returns `CitationSourceMatchSchema`** (`id`, `name`, `skip_locator`) — the web child to cite. One transaction, every created row attributed to `request.user`.
- **Re-recognize, then branch** (one `recognize_url(url)` call returns all buckets; check in this order): `rec is None` → **no match** → create the root **and** the child; `rec.identifier is not None` → **scheme identifier** (IPDB/OPDB/…) → 422 telling the caller to use `scheme:identifier` (check **before** child — a scheme hit with an existing child sets both); `rec.child is not None` → **exact child** → reuse; else (parent only) → **domain match** → create the page child under the existing root, **ignoring `site_*`** (the root already exists — it is never renamed from here). (Not routed through `get_or_create_external_source` — that patch helper writes no `created_by`/`updated_by`, breaking the every-row-attributed promise.)
- **New root, raw host — the one line PR 2 changes.** `host = normalize_host(urlparse(url).hostname)`, the pasted host as-is (PR 2 swaps to `registrable_domain(host)`). Create: the root (`source_type=web`, `name = site_name or host`, `description = site_description`), its `homepage` link `https://{host}/`, its `CitationSourceRootDomain(host=host)`, the page child, and the child's `reference` link at `url`.
- **Factor `web_child_name(url, name="")`** (in `extractors.py`) — the reviewed-name → URL → hostname (when blank or over `CITATION_SOURCE_NAME_MAX_LENGTH`) fallback now inline in `get_or_create_web_source` — and call it from both the patch path and here so the two web-child mints share one name rule. Preserve the current `hostname or url[:MAX]` truncation branch for the `hostname is None` case. The domain-match path sends no `page_name`, so the blank-name fallback stays exercised.
- **Root-create race — do not route the domain row through `_clean_and_save`.** That helper converts `IntegrityError` → `HttpError(422)`, which would swallow the race signal. Instead, the create-root branch runs in a **savepoint**: `domain.full_clean(validate_unique=False)` — so §1.2's root-only and §2.2's public-suffix `clean()` guards (plus CHECK constraints) still fire, while host-uniqueness is left to the DB — wrapped in its own `except ValidationError → HttpError(422, _validation_detail(exc))` (Django's `ValidationError` has **no** API exception handler, so an uncaught one is a 500, not the declared 422; reuse the `_validation_detail` formatter factored out of `_clean_and_save`). Then `domain.save()` with an explicit `except IntegrityError:` → roll back the savepoint, re-`recognize_url` (the root now exists) and nest the child under it. `validate_unique=False` is what guarantees the race manifests as a DB `IntegrityError` from `save()` (never a `validate_unique` `ValidationError` that the guard-catch would misread as a 422). **Same-URL child race** (two cites of one URL under a root both create a child) is an accepted benign duplicate for gardening — call it out, don't handle inline.
- **Tests:** no-match creates root + child at the raw host, all rows attributed; a domain match nests the child under the existing root and ignores `site_*`; hostless / `mailto:` → 422 (no 500); the root-create race re-recognizes and nests instead of 500ing; an exact child → reuse; a scheme URL → 422.

Run `make codegen`.

🛑 STOP for user review before committing.

### ✅ DONE: PR 1.1b — describe-site + page stages; writes only on finalize — `frontend/src/lib/components/input/citation/`

> **As built (differs from the bullets below).** The flow ended up recognition-driven rather than a single new-root path: an exact-child paste cites directly (no create steps); a domain match shows only the page step; a new site shows describe-site → page. There is **no `describe_site` reducer stage** — the state machine kept its four stages (`search`/`identify`/`create`/`locator`) and the orchestrator picks `CitationWebCreateStage` vs the authored-work form by a single `isWebSeed(seed)` check. The three web seeds (`web-url`, the web `extraction`, a domain-match seed) collapsed into one `web` seed `{url, siteName, draft}`. **The domain-match unification was folded in here** — the domain-match path now routes through `cite-url` too, and the manual "add a page under a known web root" path (identify → +create) routes through the same web page step. `CitationCreateStage` is now authored-works only (book/magazine), and a shared `DropdownButton` replaced the per-stage submit buttons. Both web paths scrape the page, so the page name prefills in every case. (Committed as `feat(citation): unify web citation create into one describe-site → page flow`.)

- **New `describe_site` stage** in the state machine, entered only on the **web new-root** path (an `extraction` or `web-url` seed with no recognized parent). Copy frames it as one-time site setup — _"This will be the first citation from this domain."_ Fields: **Site name** (prefill `og:site_name` when scraped, else blank — a blank name defaults to the domain on the backend) and an optional **Site description** (manual, blank — nothing is scraped for it). "Next" → the page step.
- **Page step:** **Page name** (prefill `og:title`, else blank) and the **URL** (confirmation; editable on a failed scrape — when the URL is most likely to need correcting). Its button is the **finalize** — a web child has `skip_locator=true`, so there is no locator step after it. **No Author or Year** on either step.
- **All writes fire on finalize, not before.** The finalize button calls `cite-url({url, site_name, site_description, page_name})`, then the existing `POST /api/citation-instances/` with the returned child. Source creation happens only on this button, so abandoning at `describe_site` or the page step writes nothing. If the instance POST fails _after_ `cite-url` succeeded an orphan root is left — **accepted** (rare, gardening-mergeable): the goal is no-litter-on-_abandon_, not all-or-nothing, so the two calls stay separate — `cite-url` keeps one job and the instance endpoint stays the universal cite sink.
- **The cited record is the web child**, never the parentless root — upholding `is_abstract`'s contract that the cited record is always a child under the matched root.
- **Docs:** update `docs/Citations.md`'s web-create section to describe the `cite-url` flow (paste → describe-site → page → child under a root). The PSL/registrable-domain governance docs still land in §2.3.
- **Tests:** dom — `describe_site` → page → finalize calls `cite-url` then the instance endpoint and cites the returned child; abandoning before finalize issues no writes; a domain-recognized URL still uses the existing `create_by_url` path (unchanged); a book / explicit-parent create still hits `create_citation_source`.

#### Unify the domain-match path onto `cite-url` — `frontend/src/lib/components/input/citation/`

Landed as part of the 1.1b unification (it was the natural way to fix the page-name asymmetry between the new-site and domain-match paths). The domain-match recognition item now scrapes the page, then hands off to the web flow's page step (Create Site skipped) and finalizes via `cite-url` — which re-recognizes server-side and nests the child under the matched root, ignoring the site fields. The inline `create_by_url` POST to `create_citation_source` is gone; one web-cite code path remains. The dom tests assert the domain-match cite nests under the parent, renders the parent name, and routes through `cite-url` (no direct `create_citation_source` POST).

🛑 STOP for user review before committing.

## PR 1.2 — reject non-DNS recognition hosts (bug → failing-test-first)

A latent bug in the merged mint paths, **no PSL needed**: both `cite-url`'s `_create_root_and_child` (§1.1a) and `create_citation_source`'s root branch (§1.5b) mint a `CitationSourceRootDomain` from the raw `urlparse(url).hostname` with no check that it's a real DNS domain. An IP literal (`192.168.1.1`, `[::1]`→`::1`), `localhost`, or any single-label / non-DNS host therefore becomes a junk recognition host — plus a junk root and homepage link — instead of a clean 422. This is independent of the PSL work; it lands here, ahead of PR 2, so §2.3's registrable-domain rounding can assume a valid DNS host.

This is a bug fix → **TDD, failing test first** (CLAUDE.md): write the reproducing test, watch it fail (today an IP-host `cite-url` returns 201 and mints a root), then fix.

- **One model-level invariant in `CitationSourceRootDomain.clean()`** — the same home as §2.2's coming public-suffix guard, and where `clean()` already normalizes the host and enforces root-only. All four mint paths converge here (`cite-url`'s `full_clean(validate_unique=False)`, `create_citation_source`'s `_clean_and_save`, the admin inline formset, patches), so one guard covers them uniformly — no per-endpoint duplication. Validate the **normalized** value (`normalize_host` runs first in `clean()`).
- **Add a pure helper to `hosts.py`** (model-free, no PSL, alongside the existing host helpers): `is_dns_host(host: Host) -> bool` — true only for a syntactically valid DNS name (dot-separated labels, each 1–63 chars of alnum/hyphen, no leading/trailing hyphen, **at least one dot**, TLD label not all-numeric) and **not** an IP literal (reject anything `ipaddress.ip_address()` parses; the bracket-stripped IPv6 `::1` is also caught by the requires-a-dot rule). `clean()` raises `ValidationError({"host": …})` when it's false. Unit-test the helper directly (no DB), parametrized like the others.
- **Plus an early guard in `cite-url`'s `_create_root_and_child`.** Right after the existing `hostname is None` guard: `host = normalize_host(hostname)`, then `if not is_dns_host(host): HttpError(422, …)`. The guard runs **after** `normalize_host` (so it receives a `Host`, honoring the type's "normalize is the only honest source" contract — [hosts.py:21]) but **before** `registrable_domain` and any DB write — so the interactive path rejects an IP/`localhost` paste with a clean early 422 and **no** create-then-rollback, and §2.3's registrable-rounding precondition is literally true here: `registrable_domain` only ever sees a valid DNS host. `create_citation_source` (raw API, no UI) needs no early guard in PR 1.2 — `clean()` is its backstop. (§2.3 later factors this guard + the new rounding into a shared `root_host_from_url` helper that **both** endpoints call, so validation-before-rounding becomes uniform; here in PR 1.2 it's just the `cite-url` early guard, no PSL.)
- **Otherwise surfaces through the existing 422 plumbing.** For the model-level rejection, `cite-url` already wraps the domain `full_clean` in the `ValidationError → HttpError(422, _validation_detail(...))` catch and `create_citation_source` mints via `_clean_and_save`, so the `clean()` guard flows through both as a 422 — the early guard above is the only new endpoint code.
- **Complete the normalized-_shape_ CHECK so recognition's `Host(stored)` trust is by-construction (separate commit — `hosts.py` + model + migration).** Recognition reads stored hosts back as `Host(candidate_host)` _trusting_ they're normalized, but today only `clean()` guarantees it, with a partial DB backstop (`field_lowercase` covers case only) — a raw-SQL/bulk insert of a denormalized host then silently fails to suffix-match. Make the normalized shape fully DB-enforced:
  - **Make `normalize_host` idempotent first.** Change it to strip **all** consecutive leading `www.` labels (`www.www.foo.com` → `foo.com`), not just one, so a normalized host can never start with `www.` (`wwworld.example.com` still keeps its label — only whole `www` labels are stripped). Update [test_hosts.py:34] (`www.www.example.com` → `example.com` now) and the `normalize_host` docstring ("strips _a_ leading `www.`" → "strips _all_ leading `www.` labels"). Bonus: recognition can no longer mint a `www.foo.com` shadow of `foo.com`.
  - **Then add both CHECKs** to `CitationSourceRootDomain`: `~Q(host__startswith="www.")` and `~Q(host__endswith=".")`, alongside the existing `field_lowercase`. The three together pin the full normalized shape at the DB for every writer, so recognition's `Host(candidate_host)` is justified by construction — delete the model docstring's "the CHECK ... can only partially cover (case, not `www.`-stripping)" concession. The migration **re-normalizes any existing rows before adding the constraints** (defensive — current data is already clean, but this keeps the constraint addition from failing on a legacy `www.www`-derived row, same caution as §2.2's audit).
  - **Tests:** `normalize_host` idempotence (`normalize_host(normalize_host(h)) == normalize_host(h)`, incl. multi-`www`); `full_clean` rejects a `www.`-prefixed and a trailing-dot host.
- **Tests (failing-first):** `cite-url` with an IPv4-literal host → 422, no root/child/domain minted (the headline repro); IPv6 literal; `localhost` / a single-label host; an invalid-label host. The same rejection via `create_citation_source` (parentless + homepage IP host → 422). A direct model-`clean()` test of the invariant. Valid multi-label hosts (`american-pinball.com`, `s4.american-pinball.com`) still accepted.

🛑 STOP for user review before committing.

## PR 2 — governance (PSL + public-suffix guard + registrable-domain rounding)

We do PR 2 in the same branch as PR 1. **NOT** a separate PR. The atomic create-from-URL endpoint already shipped in §1.1a; PR 2 only adds the PSL write-time layer: §2.1 PSL helpers → §2.2 public-suffix guard → §2.3 round minted hosts to the registrable domain.

Sections are in build order, one commit each, 🛑 STOP for user review before committing. In commit messages, do NOT reference ephemera that future readers will not understand, such as step numbers, PR numbers, links to this plan.

### 2.1 Public Suffix List

- Add `publicsuffixlist` (bundled snapshot, no network) via **`uv add publicsuffixlist==<pinned>`**, not a hand-edit of `pyproject.toml`: the repo commits `backend/uv.lock` and CI runs `uv sync --frozen`, so a `pyproject.toml`-only change leaves the lock stale and reds CI. Commit the updated `uv.lock`; verify with `uv sync --frozen` (or `make` equivalent). Add `is_public_suffix(host: Host) -> bool` and `registrable_domain(host: Host) -> Host | None` to `hosts.py` — the single `Any` boundary for the untyped dep. Scope the missing-stub suppression to a **per-module** `[[tool.mypy.overrides]]` (`module = ["publicsuffixlist", "publicsuffixlist.*"]`, `ignore_missing_imports = true`), matching the existing override block — **not** a global `[tool.mypy] ignore_missing_imports`, which would weaken strict typing for every future stubless dep. No scattered `# type: ignore`. Pure (table lookup). Used only at write/validate time, never in recognition, so matching stays PSL-free and deterministic.
- **Type with `Host`, in and out — match the module's existing `NewType` discipline.** Every helper in `hosts.py` already takes/returns `Host` (the normalized-host marker) to pin the normalize-before-compare precondition at the type level; the two new helpers join it. The return is `Host | None`, **not** `str | None`: a registrable domain _is_ a normalized host, and §2.3 feeds `registrable_domain(...)` straight into `CitationSourceRootDomain.host` (a `Host` by the model's `clean()`) and the homepage link — returning `str` would force §2.3 to re-normalize or fabricate a `Host(...)`, exactly the un-typed coercion the `NewType` forbids. All callers (`clean()` §2.2, the §2.3 rounding in `cite-url` and `create_citation_source`) already hold a normalized `Host`, so the `Host` input is free.
- **Confine the `Any` to one module-level constant.** Construct the `PublicSuffixList` object **once** at module load (a typed module-level value), so the two wrapper functions are the _only_ places the dep's `Any` is coerced to `bool` / `Host`, and nothing past their returns is `Any`. This is what earns the per-module mypy override over scattered `# type: ignore`; no per-call construction.
- **Pin the version and keep the snapshot fresh.** Pin `publicsuffixlist` to an exact version — a bundled snapshot is the whole point (deterministic, offline), but it _rots_: new subdomain-per-publisher platforms won't be recognized until the dep is bumped, silently mis-rooting them. Add a renovate/dependabot entry so the bump path exists rather than relying on someone remembering.
- **Decide `accept_unknown` explicitly — set it `True`.** `registrable_domain` must treat a host on a TLD the bundled snapshot doesn't know as having an eTLD+1 (the unknown TLD + one label), not return `None`. It's load-bearing in prod, not just tests: with `False`, a real site on a TLD newer than the snapshot 422s and can't be cited; with `True`, it roots at its eTLD+1, accepting snapshot lag. `True` is the same call the snapshot-rot worry above implies — fail open on a new TLD, not closed. (Corollary: under `True`, non-DNS garbage hosts — IP literals, `localhost` — would also "round" happily; PR 1.2's `clean()` guard rejects them at the model before any mint, so they never reach `registrable_domain` here.) Verify the exact `publicsuffixlist` kwarg name at implement time.
- **Honor the PRIVATE section — load-bearing, not incidental.** Both helpers must treat the PSL's PRIVATE rules as suffixes (the `publicsuffixlist` private flag on / `only_icann` off — verify the exact `publicsuffixlist` API at implement time). This is what keeps `legit.github.io` and `evil.github.io` distinct roots instead of collapsing onto one shared `github.io`, and what makes §2.3's registrable-domain rounding keep `someproject.github.io` whole (its own root) rather than collapsing it to `github.io`. It is consistent with Known Limitations: only **non-PSL** subdomain-per-publisher platforms collapse to the eTLD+1; PSL-private ones stay separated. With the private section honored, `is_public_suffix("github.io")` is true (so a bare `github.io` is rejected as a recognition host) and `registrable_domain("foo.github.io") == "foo.github.io"`.
- **The PRIVATE-section flag is the one silently-failing detail — pin it with a two-directional canary test.** Get the `private`/`only_icann` flag backwards and there is no error, just wrong behavior: either `github.io` becomes a valid root (the exact vacuum-hijack PR 2 exists to stop) or legit `foo.github.io` pastes start 422ing. The canary that fails iff the flag is wrong asserts **both** directions together: `is_public_suffix("github.io") is True` **and** `registrable_domain("foo.github.io") == "foo.github.io"`. Treat it as the gate on trusting the dep.
- **We don't maintain a local denylist.** The PSL (its PRIVATE section) already is the infrastructure-host list (`cloudfront.net`, `s3.amazonaws.com`, `github.io`, …); gaps go upstream, not into a forked copy.
- **Tests:** the two-directional `github.io` canary above; `is_public_suffix` true for `com`/`co.uk`/`github.io`/`cloudfront.net`, false for `american-pinball.com`; `registrable_domain` collapses `s4.american-pinball.com` → `american-pinball.com`, keeps `foo.github.io` whole (private-section coverage) and returns `None` for a bare public suffix.
- **Pin the `registrable_domain` ↔ `is_public_suffix` equivalence (§2.3 leans on it).** The API paths reject a bare public suffix via the helper's `registrable_domain(host) is None`; patches/admin reject it via `clean()`'s `is_public_suffix`. Those reject the same set _only because_ `registrable_domain(h) is None ⟺ is_public_suffix(h)` (for an otherwise-valid DNS host) — a coincidental equivalence between two guards that a library bump could silently split. Add a parametrized test asserting both sides agree across the canary hosts (`com`, `co.uk`, `github.io`, `american-pinball.com`, `s4.american-pinball.com`), so the two code paths can't diverge unnoticed.

🛑 STOP for user review before committing.

### 2.2 Public-suffix guard (model-level)

- `CitationSourceRootDomain.clean()` rejects a `host` that `is_public_suffix` — a bare `cloudfront.net` / `co.uk` can't be a recognition host, on every path (API, patch, admin). A real invariant on a dedicated model (no link polymorphism to dance around).
- **Minimal audit migration — cheap insurance against near-impossible data.** The §1.3 backfill inserted rows with no PSL guard in force, so in theory a public-suffix host could already sit in the table and silently drive recognition. In practice that needs a seeded root whose homepage is literally `https://github.io/` — very unlikely — but the failure mode (a live vacuum root) is silent and high-impact, so a few-line scan is worth it. Ship a data migration alongside the guard that scans existing `host`s and **raises listing any offenders** (host + owning root), failing the deploy rather than auto-deleting (a row may have children; a human resolves). Keep it terse — no elaborate recovery runbook in the exception; the offender list is enough.
- **Tests:** `com`/`co.uk`/`github.io` rejected via `full_clean()` **and** through the real paths that call it (API, patch, admin inline) — not via `objects.create()`, which Django never runs `clean()` on (a raw `create()` is exactly the bypass the audit migration exists to catch); `american-pinball.com` accepted; the audit migration raises on a pre-existing public-suffix row.

🛑 STOP for user review before committing.

### 2.3 Round the minted recognition host to its registrable domain — both mint paths — `api.py`

The single PSL change to the write paths: every contributor mint sets the recognition **domain** to the eTLD+1 the host belongs at (the homepage _link_ is a separate matter — see the per-path divergence below). One rule, two call sites — **round, don't reject**, so there's no raw-API-strict vs UI-forgiving asymmetry to justify. (Replaces the earlier "eTLD+1 contributor restriction" design, which rejected a subdomain on the raw API and rounded it in the UI — two behaviors for one input.)

- **One shared endpoint helper — `root_host_from_url(url) -> Host`.** Both API mint paths need the identical derivation, so factor it into one function that **validates, then rounds**: parse `urlparse(url).hostname` (`None` → 422) → `host = normalize_host(hostname)` → `if not is_dns_host(host): 422` (syntactic — IPs, single-label, malformed) → `if is_reserved_tld(host): 422` (RFC-6761/6762 special-use names — `localhost`/`invalid`/`test`/`example`/`local` — a frozen IETF set, never in the PSL and never a real registrable domain; a small `frozenset` in `hosts.py`, **not** the maintained denylist §2.1 forbids) → `reg = registrable_domain(host)` (`None` → 422 — a bare public suffix `com`/`co.uk`/`github.io` has nothing to root at) → return `reg`.
- **Call it early on both paths — before any write — so the property is uniform.** `cite-url` already does (its PR-1.2 early guard becomes this call). `create_citation_source` computes `reg` at the **top** of its parentless-homepage branch, _before_ the source and link saves ([api.py:321],[:336]) — so an invalid host 422s with **nothing written**, not a half-created source rolled back. That makes "validation precedes rounding, no create-then-rollback" true on both paths by construction — the gap an earlier draft left (it called the helper only at the mint block, after the writes, so the early-422 property held for `cite-url` alone). The helper is the single place raw-API junk is rejected.
- **Both paths round the recognition _domain_.** Set `CitationSourceRootDomain.host = root_host_from_url(url)` in both `cite-url`'s `_create_root_and_child` (§1.1a) and `create_citation_source`'s parentless branch (§1.5b). The first cite of a never-seen site via a subdomain URL (`s4.american-pinball.com/…`) thus creates the `american-pinball.com` root. A subdomain of an _already-seeded_ root never reaches this branch — recognition matches the parent and nests the child. A raw-API subdomain just-works the same way the UI does.
- **The homepage _link_ differs by path — only `cite-url` synthesizes it.** `cite-url` has no user-provided homepage URL (the user pastes a _page_ URL), so it synthesizes the homepage link at the rounded root, `https://{reg}/`, reusing the helper's `reg` — one derivation feeds both the link and the domain row. `create_citation_source`'s homepage link is the **user-submitted `data.url`** and stays as-is — display-only, decoupled from recognition, and allowed to be richer than `https://host/` (Decisions, "Homepage links stay"). So `create_citation_source` computes `reg` once up front (the early-call above) and uses it **only** for the `CitationSourceRootDomain.host`; the homepage `CitationSourceLink` still uses `data.url` ([api.py:326]) unchanged. A parentless raw-API subdomain paste therefore yields `CitationSourceRootDomain.host == "american-pinball.com"` with the homepage link **left at the submitted URL** (not rounded).
- **Patches/seeding are exempt — they keep the raw declared host.** `ensure_root_source` does **not** call the helper or round: a patch may deliberately seed a more-specific subdomain root (`twip.kineticist.com` under `kineticist.com`), the trusted, explicit path for it. Rounding is contributor-API-only — which is why it lives in the endpoint helper, not in `clean()` (`clean()` fires on the patch path too).
- **`clean()` is the endpoints' backstop, the gate for everyone else.** With `root_host_from_url` validating before rounding on both API paths, `clean()`'s `is_dns_host` and §2.2's `is_public_suffix` are pure defense-in-depth there — the _actual_ gate only for writers that bypass the helper (patches, admin inline, raw ORM). **`is_dns_host` stays purely syntactic** (IPs, single-label, malformed) on purpose: `clean()` reuses it on _every_ path including seeding, so it must not reject `.example`-style hosts the 27 seeding-test fixtures rely on. The **reserved-TLD reject lives in the helper, not `is_dns_host`** — contributor policy, exactly like rounding — so a trusted patch/admin _could_ still declare a `localhost`/`example` host (author intent, harmless), but no contributor can. Net: contributors can't mint IP, bare-label or reserved-TLD recognition hosts; a genuinely-unknown-but-real new gTLD still fails open (rounds) per `accept_unknown=True` (§2.1) — the one accepted-junk case that remains, and is meant to.
- **No contributor edit-recognition-host endpoint** — admin owns recognition-host edits via the §1.6 inline; `update_citation_source_link` is unguarded because the homepage link is display-only and decoupled from recognition.
- **Migrate the API-path tests off `.example` — grep, don't enumerate.** `.example` is now a reserved TLD the **helper rejects** (Finding 2), so every test that roots/mints through `root_host_from_url` (`cite-url`'s no-match branch, `create_citation_source`'s parentless mint) will 422 on a `.example` host instead of creating a root. Switch each to a real registrable domain (`newsite.com` / `blog.newsite.com`). **Don't trust a hard-coded list** — an earlier draft's five-name list already missed `test_response_is_the_web_child` (roots `newsite.example/p`). `grep` the citation tests for `.example` and migrate every one that **roots a new source or mints a `CitationSourceRootDomain` through an API endpoint** (e.g. `test_any_root_type_mints_domain`, `pinball-book.example`; `test_root_domain_guard_failure_returns_422_not_500`, `blocked.example` — which does reach the root-create path, patching `full_clean` to raise; there's no SSRF guard despite the name). **Leave the `clean()`-path `.example` fixtures alone** — the seeding (`test_seeding`, 27 refs) and migration-backfill tests go through `clean()`, whose syntactic `is_dns_host` does **not** reject reserved TLDs, so they keep working unchanged.
- **Docs.** Add the PSL / public-suffix-guard / registrable-domain-rounding governance docs to `docs/Citations.md` in this commit (this is where the PSL write-time layer lands). The `recognize_url` / `CitationSource` docstrings and the step-3 / homepage-link rewrites already landed in §1.4.
- **Tests:** **update** `test_no_match_creates_root_and_child_at_raw_host` — it currently _pins_ raw-subdomain rooting (`blog.* → host == blog.*`), which this flips, so its assertions invert to the registrable domain; **add** cite-url no-match rounds `s4.american-pinball.com/…` up to the `american-pinball.com` root — asserting **both** `CitationSourceRootDomain.host` and the synthesized `homepage.url == "https://american-pinball.com/"` — and a bare public suffix → 422; `create_citation_source` with a subdomain homepage rounds `CitationSourceRootDomain.host` to the registrable domain (no reject) **while leaving `homepage.url` at the submitted subdomain URL**; a reserved-TLD host (`x.localhost`, `foo.example`) → 422 on **both** API endpoints (helper reject) but is still acceptable through a patch's `clean()` path; a patch may still seed a subdomain root. (The §1.1a bucket/race/attribution tests cover the rest.)

🛑 STOP for user review before committing.

## Cleanup — `link_type` hygiene (independent of PSL/governance)

This work has **nothing to do** with the PSL/eTLD+1 governance of PR 2 — it's pulled out so each concern is reviewed on its own. It rides in the same branch but is three independent commits that can land in any order (the natural order below is faucet → floor). Citation models extend `TimeStampedModel` only — **not** `ClaimControlledModel` — so the data reclassification is a plain `UPDATE` migration with no provenance/claims dance.

Sections are one commit each, 🛑 STOP for user review before committing.

### C1 — Fix the `link_type` default footgun (bug → failing-test-first) — `api.py`, `schemas.py`

A live bug generator: as long as [api.py:327] reads `link_type = data.link_type or "homepage"`, every `create_citation_source` call under a parent with an omitted `link_type` mints a _new_ mistyped child `homepage` link. This is a bug fix → **TDD, failing test first** (CLAUDE.md): assert a parent-context create with no `link_type` produces a `reference` link, watch it fail, then fix.

- Change the create schema's `link_type` default from `"homepage"` to `None` ([schemas.py:207-210]) — the schema default currently shadows the `or` — AND make `create_citation_source` parent-aware. Resolve to **`LinkType` enum members, not string literals**: `data.link_type or (LinkType.HOMEPAGE if parent is None else LinkType.REFERENCE)` (members are `str` subclasses, so behavior-identical; matches the model side, which already uses `LinkType.REFERENCE`, and closes the stringly-typed seam between api.py's `"homepage"` literal and the model).
- Recognition is unaffected: the root-domain mint is gated on `parent is None` at [api.py:345], so a mistyped child link never drove matching — this is data hygiene, not a recognition bug.
- **Tests:** the failing-first parent-context default test above; a parentless create with no `link_type` still defaults to `homepage`.

🛑 STOP for user review before committing.

### C2 — Enum-type the four schema `link_type` fields — `schemas.py`

Today each is `str` with a free-form description listing the valid values — a Literal enforced only by the DB CHECK (`citation_citationsourcelink_link_type_valid`), invisible to the type system and the frontend. Type them as the model's `LinkType` `TextChoices` (Ninja/pydantic accepts a Django `TextChoices` as a field type; members are `str` subclasses, so the on-the-wire value is unchanged).

- The four sites: `CitationSourceLinkSchema` ([schemas.py:304], output) → `LinkType`; `CitationSourceCreateSchema` ([:207], input) → `LinkType | None = None` (consistent with C1's default change); `CitationSourceLinkCreateSchema` ([:355], input, required) → `LinkType`; `CitationSourceLinkUpdateSchema` ([:365], partial) → `LinkType | None = None`. Drop the value-listing from each `description` — the enum carries the allowed values into OpenAPI — keeping only the purpose text.
- **Validation moves to the boundary (intended, stricter).** An invalid `link_type` now 422s at parse instead of erroring at `save()`. **Keep the DB CHECK** — it still guards the non-API writers (patches, admin, raw ORM); the schema enum is the earlier, friendlier gate, not a replacement.
- **Wire-shape change → frontend.** Run `make codegen`; `link_type` regenerates as a typed union on both read and write schemas. Check the frontend consumers still compile against the narrowed type, and per CLAUDE.md derive any local subset from the generated name rather than redeclaring the literal.
- **Tests:** an invalid `link_type` on the create / link-create / link-update inputs → 422 at the Pydantic boundary (not a DB `IntegrityError`); each valid member accepted; the output schema serializes the bare value string (`"homepage"`, not `"LinkType.HOMEPAGE"` — the pydantic-v2 enum-serialization trap).

🛑 STOP for user review before committing.

### C3 — Reclassify the 145 existing child `homepage` links → `reference` (data migration) — `migrations/`

Purely cosmetic floor-mopping, optional, depends on nothing in C1/C2. One-off plain `UPDATE` data migration (not claim-controlled, per above): set `link_type = "reference"` on every child (`parent_id IS NOT NULL`) `homepage` link. Lands after C1 shuts the faucet so it doesn't immediately re-accumulate.

- **Tests:** the migration reclassifies child `homepage` links and leaves root `homepage` links untouched.

🛑 STOP for user review before committing.

## Verification

```bash
cd backend && uv run pytest apps/citation -q
uv run python manage.py migrate
uv run python manage.py shell -c "from apps.citation.extractors import recognize_url; print(recognize_url('http://s4.american-pinball.com/games/gtf/docs/manual.pdf'))"
# → Recognition(parent_name='American Pinball', ...)
uv run python manage.py shell -c "from apps.citation.models import CitationSource as C; print(C.objects.filter(parent__isnull=True, name__icontains='week in pinball').count())"
# → 1   (root 49 gone)
make mypy && make quality   # quality = lint + codegen + frontend svelte-check, in that order; Cleanup C2 changes generated API types, so the frontend check must run after codegen (plain `make lint` skips svelte-check entirely)
```

Prod: the PR 1 migration **backfills root-domains** on deploy — it does **not** delete root 49. The duplicate root-49 cleanup is the separate guarded **manual** step (§1.3) and must already have run (before this migration deploys), or the backfill audit trips on the twip collision.

## Known limitations

- **Asset hosts on a different registrable domain** (a third-party CDN like `…cloudfront.net`, or any host not under the publisher's domain) won't match — longest-suffix only collapses within one registrable domain. These need an extra `CitationSourceRootDomain` row on the root (a deliberate alias) or a separate root.
- **Non-PSL "subdomain-per-publisher" platforms** collapse to one shared registrable-domain root under the eTLD+1 rule until an admin gardens them apart.

## Deferred

- **Admin "promote a subdomain into its own root" gardening tool** — creates a more-specific root and reparents the children that now route to it (an explicit, visible move, trusted-only). The single home for reparenting. Until then, creating a more-specific root leaves existing children under the ancestor (a temporary split); a child's parent is set at cite time and not retroactively maintained.

## Never'ed

- **Delete + reparent** — a source with children must never be deletable; `on_delete=PROTECT` on the parent FK enforces it. No code reparents on delete.
- **Auto-reparent on save** — rejected; it bred `save()`-side-effect complexity. Regrouping is deliberate gardening.
- **Fold TWIP into Kineticist** — keep root 406 as its own publication.
