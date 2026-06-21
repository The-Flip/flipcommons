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
- **Rewrite the recognition docs in this commit, not PR 2.** Recognition behavior changes _here_, so its docs change here. Rewrite the `recognize_url` docstring — the current working-tree edit at [extractors.py:128-138] argues _against_ subdomain loosening and is now superseded — and `docs/Citations.md`'s step-3 + homepage-link explanation, to describe `CitationSourceRootDomain` as the recognition signal and the longest-suffix subdomain match. PR 2's §2.6 keeps only the PSL/eTLD+1 doc additions.
- **Tests:** `s4.american-pinball.com/…` → American Pinball; `twip.kineticist.com/…` → the TWIP root (most specific) when one exists, else the Kineticist root; a deeper subdomain → nearest root.

🛑 STOP for user review before committing.

### ✅ DONE: 1.5a Seeding typing cleanup (prep, no behavior change) — `backend/apps/citation/seeding.py`

Pure refactor, landed _before_ §1.5b so the host-dedup commit is behavior-only and reviewable in isolation. Make `_lookup_source`'s return a `NamedTuple` and replace the `dict[str, object]` field-bags (`_source_fields`/`_create_source`) with a `str | int | None` alias, lifting `parent` to a typed param. No functional change; the existing seeding tests stay green. (§1.5b reshapes this resolver — it must also consider hosts and distinguish matched-by-host from matched-by-name — so the `NamedTuple`'s fields will likely widen there; that's fine, 1.5a just tightens the existing shapes.)

🛑 STOP for user review before committing.

### ✅ DONE: 1.5b Creation + seeding dedup — `backend/apps/citation/{api.py,seeding.py}`

Creation and dedup ship together: without dedup, re-seeding a root under a cosmetically different name would create a second root and trip the `host` `unique` (an `IntegrityError` that wedges the patch queue).

- **Homepage-typed links only.** Throughout this section, "declared homepage host(s)" means the hosts of a node's `link_type='homepage'` links (matching the §1.3 backfill and the create paths) — non-homepage links (`catalog`/`reference`/…) contribute no recognition host. For `create_citation_source` the homepage link is the single attached `url` when `(data.link_type or "homepage") == "homepage"`.
- **Root creation makes a root-domain row — any-root, not web-only.** Wherever a parentless source is created with a homepage link — `ensure_root_source` (patch `sources:`) and `create_citation_source` (parent-less, homepage link) — also create `CitationSourceRootDomain(host=normalize_host(urlparse(homepage_url).hostname))`, regardless of `source_type` (matching the §1.3 backfill and current recognition; see the any-root decision). Skip when `hostname` is `None` — `URLField` makes that near-impossible, but honor §1.1's None→skip contract. **full_clean the row** (the `_clean_and_save` pattern, not a raw `.create()`) so §1.2's root-only `clean()` and §2.2's public-suffix `clean()` actually fire. Mint after the source/link exist, inside the **existing** `transaction.atomic` — no savepoint (an `IntegrityError` exits the block and rolls back; the savepoint dance is §2.4's concern). The homepage link is still created (display). Children get none.
- **API path mints but does not dedup.** `create_citation_source` only mints; it does **not** run the host-dedup below (that's seeding-only; the interactive create-from-URL dedup is §2.4). A user creating a root whose host another root already owns therefore hits the `host` `unique` — surface it as a friendly **422** via `_clean_and_save`'s `integrity_msg` ("That domain is already recognized by another source"), not the raw DB message.
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

## PR 1.1 — describe-site stage + deferred-write web create

The interactive web-create flow should have two properties that don't depend on the PSL, so they land here ahead of PR 2:

- **Writes happen only on finalize** — nothing is created until the contributor commits the citation, so an abandoned flow leaves no half-described root.
- **A pasted web URL cites a page child** under its site root, never the bare root — upholding `is_abstract`'s contract that the cited record is always a child under the matched root.

PR 1.1 delivers both: a `cite-url` endpoint that creates the site root and the page child, and a "describe this new site" stage. It needs no new dependency — `cite-url` roots at the **raw** host here, and §2.4 rounds it to the registrable domain once the PSL lands.

**Scope: the new-web-root path only** — a pasted web URL whose domain no root yet owns. A domain _match_ recognized at search uses the "Cite a page under **X**" → `create_by_url` path (it writes only on the click); book/magazine and explicit-parent creates use `create_citation_source` (a book root is concrete and citable — no describe-site step). §2.5 optionally unifies the domain-match path onto `cite-url`.

### Decisions

- **Site name** = scraped `og:site_name` (the extract draft's existing `publisher` field) when present, else the **domain**. The fallback-to-domain lives on the backend (root `name = site_name or host`), so the Site field can prefill with `og:site_name` or sit blank and still produce a sensible root name.
- **No description scrape.** `og:description` is page-level, not site-level, so it isn't used. The Site description is an **optional, manual** field — blank by default. (Nothing new to scrape, so the extract draft and its cache key are untouched.)
- **No Author/Year anywhere in the web flow** — neither the describe-site step (site-level) nor the page step (Page name + URL only). A web citation is a site plus a page; Author and Year belong to authored, dated works (books, magazines).
- **Raw host now, registrable domain in §2.4.** PR 1.1 roots a new source at the **raw pasted host** (`normalize_host`); §2.4 rounds that to `registrable_domain` once the PSL lands. A brand-new **subdomain** paste (`blog.newsite.com`, `newsite.com` not yet seeded) therefore roots at the subdomain until §2.4 rounds it; both land in the same branch, so the un-rounded form never reaches prod.

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

### PR 1.1b — describe-site + page stages; writes only on finalize — `frontend/src/lib/components/input/citation/`

- **New `describe_site` stage** in the state machine, entered only on the **web new-root** path (an `extraction` or `web-url` seed with no recognized parent). Copy frames it as one-time site setup — _"This will be the first citation from this domain."_ Fields: **Site name** (prefill `og:site_name` when scraped, else blank — a blank name defaults to the domain on the backend) and an optional **Site description** (manual, blank — nothing is scraped for it). "Next" → the page step.
- **Page step:** **Page name** (prefill `og:title`, else blank) and the **URL** (confirmation; editable on a failed scrape — when the URL is most likely to need correcting). Its button is the **finalize** — a web child has `skip_locator=true`, so there is no locator step after it. **No Author or Year** on either step.
- **All writes fire on finalize, not before.** The finalize button calls `cite-url({url, site_name, site_description, page_name})`, then the existing `POST /api/citation-instances/` with the returned child. Source creation happens only on this button, so abandoning at `describe_site` or the page step writes nothing. If the instance POST fails _after_ `cite-url` succeeded an orphan root is left — **accepted** (rare, gardening-mergeable): the goal is no-litter-on-_abandon_, not all-or-nothing, so the two calls stay separate — `cite-url` keeps one job and the instance endpoint stays the universal cite sink.
- **The cited record is the web child**, never the parentless root — upholding `is_abstract`'s contract that the cited record is always a child under the matched root.
- **Docs:** update `docs/Citations.md`'s web-create section to describe the `cite-url` flow (paste → describe-site → page → child under a root). The PSL/eTLD+1 governance docs still land in §2.6.
- **Tests:** dom — `describe_site` → page → finalize calls `cite-url` then the instance endpoint and cites the returned child; abandoning before finalize issues no writes; a domain-recognized URL still uses the existing `create_by_url` path (unchanged); a book / explicit-parent create still hits `create_citation_source`.

🛑 STOP for user review before committing.

## PR 2 — governance (PSL + eTLD+1 + atomic create endpoint)

We will do PR 2 in the same branch as PR 1. **NOT** a separate PR.

Sections are in build order, one commit each, 🛑 STOP for user review before committing. In commit messages, do NOT reference ephemera that future readers will not understand, such as step numbers, PR numbers, links to this plan.

### 2.1 Public Suffix List

- Add `publicsuffixlist` (bundled snapshot, no network) to `backend/pyproject.toml`. Add `is_public_suffix(host) -> bool` and `registrable_domain(host) -> str | None` to `hosts.py` — the single `Any` boundary for the untyped dep (`ignore_missing_imports` in `[tool.mypy]`, no scattered `# type: ignore`). Pure (table lookup). Used only at write/validate time, never in recognition, so matching stays PSL-free and deterministic.
- **Honor the PRIVATE section — load-bearing, not incidental.** Both helpers must treat the PSL's PRIVATE rules as suffixes (the `publicsuffixlist` private flag on / `only_icann` off — verify the exact `publicsuffixlist` API at implement time). This is what keeps `legit.github.io` and `evil.github.io` distinct roots instead of collapsing onto one shared `github.io`, and what makes §2.4's registrable-domain rounding keep `someproject.github.io` whole (its own root) rather than collapsing it to `github.io`. It is consistent with Known Limitations: only **non-PSL** subdomain-per-publisher platforms collapse to the eTLD+1; PSL-private ones stay separated. With the private section honored, `is_public_suffix("github.io")` is true (so a bare `github.io` is rejected as a recognition host) and `registrable_domain("foo.github.io") == "foo.github.io"`.
- **We don't maintain a local denylist.** The PSL (its PRIVATE section) already is the infrastructure-host list (`cloudfront.net`, `s3.amazonaws.com`, `github.io`, …); gaps go upstream, not into a forked copy.
- **Tests:** `is_public_suffix` true for `com`/`co.uk`/`github.io`/`cloudfront.net`, false for `american-pinball.com`; `registrable_domain` collapses `s4.american-pinball.com` → `american-pinball.com`, keeps `foo.github.io` whole (private-section coverage) and returns `None` for a bare public suffix.

🛑 STOP for user review before committing.

### 2.2 Public-suffix guard (model-level)

- `CitationSourceRootDomain.clean()` rejects a `host` that `is_public_suffix` — a bare `cloudfront.net` / `co.uk` can't be a recognition host, on every path (API, patch, admin). A real invariant on a dedicated model (no link polymorphism to dance around).
- **Audit existing rows when this lands.** The already-committed §1.3 backfill inserts root-domain rows with no PSL guard in force (`clean()` only blocks _new_ writes after this lands), so a public-suffix host can reach `CitationSourceRootDomain` and silently drive recognition — both on prod (the §1.3 backfill runs in the same deploy, just earlier in the migration order) and on any fresh DB that re-runs §1.3 before this guard. Ship a data migration alongside the guard that scans existing `host`s for public suffixes and **raises listing any offenders** (don't auto-delete — a row may have children routing to it; a human resolves), so deploy fails loud rather than leaving a live vacuum root.
- **Tests:** `com`/`co.uk`/`github.io` rejected on write; `american-pinball.com` accepted; the audit migration raises on a pre-existing public-suffix row.

🛑 STOP for user review before committing.

### 2.3 eTLD+1 contributor restriction — `api.py`

- **Guards exactly one contributor path: the recognition host minted by §1.5b's `create_citation_source` branch for a parentless root.** Reject a host that isn't its own eTLD+1 (`registrable_domain(host)`), with an error naming the registrable domain. Keyed on **a `CitationSourceRootDomain` being minted, not on `source_type`** — root-domains are any-root (Decisions), so a contributor making a non-web root with a subdomain homepage host must be guarded too; the anti-fragmentation rule is about the recognition host, not the medium. That mint is the only place a contributor sets a recognition host:
  - `cite-url` (§2.4) auto-roots at the registrable domain by construction, so it needs no check.
  - There is **no contributor edit-recognition-host endpoint** — admin owns recognition-host edits via the §1.6 inline.
  - `update_citation_source_link` is **not** guarded: the homepage `CitationSourceLink` is display-only and decoupled from recognition (Decisions), so its host has no bearing on matching — policing it would be pointless.
- Patches are exempt (trusted) — they may seed subdomain roots (`twip.kineticist.com`).
- **Tests:** `create_citation_source` for a parentless root rejects a subdomain host (message points at the registrable domain) and accepts the registrable domain; the same rejection fires for a non-web root (any-root coverage); a patch may create a subdomain root.

🛑 STOP for user review before committing.

### 2.4 Harden `cite-url` with the PSL — `api.py`

`cite-url` (built in §1.1a) already handles the request shape, the recognition buckets, the savepoint root-create race, the shared `web_child_name` fallback, per-row attribution, and the response. §2.4 adds the one thing that needs the PSL — a new source roots at its **registrable domain**, the eTLD+1 a recognition host belongs at:

- **Root a new source at its registrable domain.** In the no-match branch the new root's host is `registrable_domain(host)`, so the first cite of a never-seen site via a subdomain URL (`s4.american-pinball.com/…`) creates the `american-pinball.com` root, and its `CitationSourceRootDomain` and homepage link (`https://{registrable_domain}/`) use that registrable host. (A subdomain of an _already-seeded_ root never reaches this branch — recognition matches the parent and nests the child.)
- **422 on a bare public suffix.** `registrable_domain(host)` returns `None` for `com` / `co.uk` / a bare `github.io` → 422 (there is nothing to root at).
- §2.4 is just the registrable rounding and the bare-suffix guard, both in the `_create_root_and_child` helper: a single `host` derivation feeds the homepage link _and_ the domain row, so the rounding is a one-place change, and the `registrable_domain(host) is None → 422` guard sits beside the existing `hostname is None` guard. `cite-url`'s child-under-root cite and finalize-only writes already hold from §1.1a.
- **Migrate the §1.1a no-match tests off `.example` hosts first.** The §1.1a cite-url tests root new sites at `*.example` hosts (`newsite.example`, `blog.newsite.example`, `raced.example`, `blocked.example`). `.example` is an RFC-6761 reserved TLD the PSL data file doesn't list, so once `registrable_domain` is applied here its result is config-dependent (eTLD+1 vs `None`, per §2.1's unknown-TLD setting) — a `None` would 422 and fail these. Switch them to a real registrable domain (`newsite.com` / `blog.newsite.com`) so correctness doesn't hinge on `accept_unknown`. Affected: `test_no_match_creates_root_and_child_at_raw_host`, `test_no_match_attributes_every_row_to_caller`, `test_blank_site_name_falls_back_to_host`, `test_root_domain_guard_failure_returns_422_not_500`, `test_root_create_race_re_recognizes_and_nests`.
- **Tests:** **update** `test_no_match_creates_root_and_child_at_raw_host` — it currently _pins_ raw-subdomain rooting (`blog.* → host == blog.*`), which §2.4 deliberately flips, so its assertions invert to the registrable domain; **add** no-match rounds `s4.american-pinball.com/…` up to the `american-pinball.com` root and a bare public suffix → 422. (The §1.1a bucket/race/attribution tests cover the rest.)

🛑 STOP for user review before committing.

### 2.5 Unify the domain-match path onto `cite-url` (optional) — `frontend/src/lib/components/input/citation/`

§1.1b already routes the new-root web path through `cite-url` (describe-site → page → finalize), made the Site/Page split a real stage, defers writes to finalize, and cites the child. The only web-cite call site still on `create_citation_source` is the **domain-match** recognition item (`create_by_url`, bucket 3) — which already cites a child and writes only on the click, so it's correct, just not uniform.

- Optionally point `create_by_url` at `cite-url` too (send `{url, page_name}`; cite-url re-recognizes and nests the child under the matched root, ignoring site fields). Win: one web-cite code path, and the server re-recognizes rather than trusting a frontend `parentId`. Low-value polish — defer or skip if the churn isn't worth it.
- **Tests (only if done):** a domain-match cite still nests the child under the parent and renders the parent name; the existing dom tests stay green.

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
