# Plan: citation domain improvements

> **Superseded.** This intermediate plan's Phase 1 is replaced by [CitationsCleanup.md](CitationsCleanup.md) (rebuilt around the `CitationSourceTypeStrategy` + `recognize_url` tidy of [CitationWriteLayerDebt.md](CitationWriteLayerDebt.md) §4), and its Phase 2 by [CitationDomainGovernance.md](CitationDomainGovernance.md) (which also now owns _enabling_ subdomain matching — the cleanup branch ships exact matching only). Kept as history; the design rationale below is still the spine those two carry forward. Work from the two current plans.

Supersedes `WebCitationDomains1.md`. Same goal — subdomain matching, domain dedup, no mistyped recognition hosts. It organizes the write paths around a **derive-vs-declare** model for recognition hosts, and adds the thing v1 missed: an honest reckoning with how the system _already_ creates citation sources from URLs, in particular the **patch-apply** path (`get_or_create_web_source`), which is where Context problem #1 actually fails.

## Two distinctions, kept separate

Earlier drafts conflated these; keeping them apart is what makes the plan small.

1. **Where a recognition host comes from — derive vs declare.**
   - **Derive:** a contributor pastes a fuzzy _page_ URL; the system rounds it to the registrable domain. Exactly one place: `cite-url`.
   - **Declare:** a curator states the host verbatim (patch `homepage:`/`domains:`, Django admin). Stored as-is.
2. **How a URL resolves to a citable source — one read, two orchestrations, a shared leaf.** Both the interactive editor (`cite-url`) and patch application (`get_or_create_web_source`) resolve a URL the same way: through **`recognize_url`** (the read path) and a **shared child-minting leaf**. They differ only in _policy_ at the edges (what to do on no match, scheme handling, attribution) — and those genuinely differ, so the orchestrations stay separate. They are not merged.

The keystone is that `recognize_url` is already shared. Fixing it (longest-suffix subdomain matching, on the branch) fixes Context #1 for **both** surfaces at once.

## Context

Authoring web citations (UI and data patches) hit three problems:

- **Subdomains aren't matched.** A claim citing `s4.american-pinball.com/manual.pdf` (an American Pinball asset host) isn't recognized as American Pinball even though `american-pinball.com` is seeded — so `get_or_create_web_source` raises `DoesNotExist` at **patch-apply** time, and the interactive editor offers "create a new source". Both because `recognize_url` matched only by exact host (modulo `www.`).
- **Web roots aren't deduped by domain.** Roots **49** `This Week in Pinball (TWiP)` (empty) and **406** `This Week in Pinball` (2 children) both point at `twip.kineticist.com` — the `sources:` dedup key `(name, source_type)` never looks at URLs.
- **Child sources carry mistyped `homepage` links.** ~145 `homepage`-typed links on _child_ sources (a fixed seed-ingest bug, commit `4618b914`), plus `create_citation_source` defaulting an omitted `link_type` to `"homepage"`. Cosmetic (recognition ignores `link_type`).

## Already on the branch — kept as-is

Built (committed locally, not pushed); the re-architecture leaves these alone:

- **`CitationSourceRootDomain` model + table** — `source FK [CASCADE]`, `host` `unique`, root-only `clean()`. (§P2.2 adds the universal predicate to `clean()`; the table shape is unchanged.)
- **`recognize_url` — longest label-boundary suffix** over `CitationSourceRootDomain.host`, **PSL-free**, deterministic, offline. **This is the shared read path** for both `cite-url` and `get_or_create_web_source`, so it already fixes Context #1 on both surfaces. Unchanged.
- **The backfill migration** — existing rows came from real roots' homepage hosts, stored **verbatim/un-rounded**. All still valid with no re-normalization — and this is _why_ declaration is verbatim: it matches what's already in prod.
- **`hosts.py` primitives** — `Host`, `normalize_host`, `label_suffixes`, `longest_suffix_match`. (`normalize_host` gets an idempotence fix in §P1.4; the rest unchanged.)
- **The exact-link-matches-child fix**, the **`web_child_name` rule** (already shared by the interactive and patch child mints), and the **frontend** describe-site → page flow / `cite-url` endpoint contract. Server-side changes here don't touch the frontend.
- **The manual root-49 cleanup** (delete the empty TWiP duplicate, guarded) — already planned/done; §P2.4 dedup keeps it from recurring.

## The shape

- **The funnel — `root_host_from_url(url) -> Host`** (`hosts.py`, HTTP-free). The single place a fuzzy URL becomes a canonical recognition host: `urlparse(url).hostname` → `normalize_host` → `is_dns_host` → `is_reserved_tld` → `registrable_domain` (`None` = bare public suffix) → return the rounded `Host`. Each gate raises a typed **`HostError(reason)`**. Its **only caller is `cite-url`'s no-match branch** (the patch path _raises_ on no match — see below — so it never derives a root). Kept pure/HTTP-free for unit-testability, a thin endpoint, and one documented validate-before-round order — a deliberate choice over inlining into the endpoint with `HttpError`.
- **Declare paths take the host verbatim.** Patch `homepage:` (its host) and `domains:` (one or more), and the Django admin inline. Each is `urlparse → normalize_host`, then the universal `clean()` predicate — **no funnel, no rounding, no reserved-TLD reject** (a curator is trusted to mean what they wrote). **Source-type-blind:** a book/magazine root that declares a `homepage:`/`domains:` host still mints a recognition row — v1's "any root type is URL-recognizable" decision is preserved on the declare path.
- **The shared child-minting leaf — `create_web_child(parent, url, name="", *, created_by=None)`.** Both `cite-url`'s no-match/domain-match branch and the patch path's domain-match branch create the same thing: a page child + `reference` link under a root. Today that's duplicated — `_create_web_child` (validated + attributed) vs `get_or_create_web_source`'s inline `.objects.create` (no `clean()`, no attribution). §P1.2 factors one validated helper both call.
- **`create_citation_source` sheds web entirely** — not just the recognition mint. It currently does four things with a URL: mints a recognition domain (removed), creates a web _root_ (parentless + homepage — never via UI), creates a web _child_ (explicit-parent "add a page" — [CitationWebCreateStage.svelte:149](frontend/src/lib/components/input/citation/CitationWebCreateStage.svelte#L149) POSTs `parent_id` + `url` + `reference`, byte-for-byte what `create_web_child` produces), and builds a scheme child's canonical link. §P1.2 routes each of these to its own leaf: web roots → `cite-url`, web children → a thin endpoint over `create_web_child`, **scheme children → a lifted-out `get_or_create_scheme_child` leaf** (shared with the patch `get_or_create_external_source`), authored-works roots add links via the link endpoint. `create_citation_source` then **drops the `url`/`link_type` fields and its entire link-mint block**, leaving one coherent job: create a root (book/magazine) or a linkless authored child. It **never touches `url`/`homepage`/`CitationSourceRootDomain`/links again** — stronger than "reject parentless + url", and matching the model's shape (concentrate web/scheme child creation in the recognition-aligned leaves). With **no** link mint left, Cleanup C1's footgun is genuinely gone.
- **The universal predicate lives in `clean()`** (every write path, incl. raw ORM): normalized **and** `is_dns_host` **and** `not is_public_suffix` (plus root-only). The funnel adds **`is_reserved_tld` reject + round** on top — _derivation policy_, which is why it's in the funnel, not `clean()`. So a curator can declare a subdomain (`twip.kineticist.com`) or even a reserved-TLD host verbatim; a contributor pasting a URL gets it rounded and reserved-TLDs rejected.

Why this is the simplest shape:

- **Rounding has one home** (`cite-url`'s no-match branch) → the funnel has one caller, no `allow_subdomain` flag, no per-path round-vs-not branch.
- **The patch-apply path needs no behavior change** — `recognize_url` (shared, already fixed) makes its domain match work for subdomains. §P1.2 only _dedups_ its child-mint onto the shared validated leaf; it doesn't re-implement it.
- **Patches behave exactly as they do today** (verbatim `homepage:`) → **no flippatch migration.** `homepage: https://twip.kineticist.com/` stores `twip.kineticist.com` verbatim — correct _and_ matching the backfilled prod row.
- **Dedup is always exact-host** — every stored host is canonical-from-`cite-url` or verbatim-from-a-curator. Suffix matching lives only in `recognize_url`.

## Decisions

- **Own the recognition host as a fact** (`CitationSourceRootDomain`), decoupled from the display `homepage` link. Set at creation; thereafter independent of display-link edits.
- **Homepage links are display-only and may be richer than `https://host/`.** A root's recognition hosts are the `homepage:` host (if any) ∪ the `domains:` list (declare), or the rounded host (`cite-url` derive). Never read back out of a link afterward.
- **Recognition is longest-suffix and PSL-free.** Rounding (PSL) is a write-time concern in the funnel only.
- **`accept_unknown=True`** for `registrable_domain` — fail open on a TLD newer than the bundled PSL snapshot. `is_reserved_tld` still rejects RFC special-use names, so the only accepted-junk case is a genuinely-unknown **real** gTLD — intended.
- **Right-size to the threat model.** Volunteer-run museum catalog, Activity-gated contributors, admin gardening — not a hostile public API. `clean()` is the gate for every _real_ writer; no CHECK constraints, re-normalizing migration, or audit migration. (Note the one _real_ `clean()` bypass today — the patch path's `.objects.create` — which §P1.2 closes by routing through the validated leaf, so the "universal" claim stops being aspirational.)

## Build plan — two phases

**Context #1 (subdomain match) and #2 (domain dedup) are already fixed on the branch** — `recognize_url`'s longest-suffix matching and the seeding host-dedup are built. So the remaining work splits cleanly:

- **Phase 1 — stabilize the creation layer.** Behavior-preserving refactors (plus two flagged behavior changes) that converge the tangled, inconsistently-validated write paths onto a few named pieces. Lands and verifies **first**, so the new behavior never rides on the shaky parts. This is the get-well work, scoped to exactly the debt the feature touches.
- **Phase 2 — domain governance.** PSL rounding (`cite-url` derive) + the `domains:` verb — the anti-fragmentation layer and multi-host capability. New behavior on the clean foundation; **more deferrable**, since the Context bugs are already closed.

One commit each, 🛑 STOP for user review before committing. In commit messages, do NOT reference ephemera that future readers will not understand, such as step numbers, PR numbers, links to this plan.

## Phase 1 — Stabilize the creation layer

Behavior-preserving except two deliberate changes, both flagged below: patch child creates now `full_clean` (can newly reject malformed historical URLs — dev rebuild is the gate), and interactive identifier re-cite becomes idempotent. Largely verified by the existing test suite still passing.

### P1.1 — name the root/child distinction — `models.py`

The root-vs-child rule is re-spelled ~23 times across `api.py`, `extractors.py`, `models.py`, `seeding.py`, `admin.py` (`parent__isnull` filters, `parent_id is None` checks). Every feature re-derives it — the seam the recurring bites keep touching. **Do not split the model** (roots and children share most fields; the self-referential tree is right). Just **give the distinction one name**:

- `CitationSourceQuerySet.roots()` / `.children()` (on a manager) — replace every `filter(parent__isnull=…)` / `filter(…__parent__isnull=…)` in app code.
- `CitationSource.is_root` property (`parent_id is None`) — replace every instance-level `parent_id is None`.
- **Leave the CHECK-constraint `Q()` conditions** ([models.py:175,221,231](backend/apps/citation/models.py#L175)) as-is — a manager method can't appear in a constraint. App-code re-spellings only.

🛑 STOP.

### P1.2 — two validated child leaves — `api.py`, `extractors.py`

The system has several child constructors with **inconsistent discipline** — `.objects.create` (no `clean()`, no attribution) in `extractors.py` vs `_clean_and_save` in `api.py`. Converge web- and scheme-child minting onto two `full_clean`-validated leaves; this also closes the one _real_ `clean()` bypass (the patch path's `.objects.create`), so the "every write validates" claim stops being aspirational.

- **`create_web_child(parent, url, name="", *, created_by=None)`** — child `CitationSource` + `reference` link, both `full_clean`d. Replace `_create_web_child` and `get_or_create_web_source`'s inline `.objects.create` ([extractors.py:365](backend/apps/citation/extractors.py#L365)). (`web_child_name` already shared.)
  - **Attribution: `created_by is None` → leave `created_by`/`updated_by` _unset_ (null)** (`null=True` on both, [models.py:111-123](backend/apps/citation/models.py#L111)) — **not** a system user. Preserves today's ingest semantics (patch children tie to the `ingest_run`). Interactive passes `request.user`; patch passes nothing.
  - **Stricter than today — can newly reject data.** `URLField` format is validated only in `full_clean`, not at the DB, so `.objects.create` tolerated a malformed page URL that `create_web_child` now raises on. Right behavior, but a behavior change — a historical patch with a marginal URL could fail. **The dev rebuild is the gate** (re-applies every patch through the new path; fix the offending URL there).
- **`get_or_create_scheme_child(root, identifier, *, created_by=None)`** — `get_or_create` the `(root, identifier)` child + `reference` link at `extractor.build_url(identifier)`, `full_clean`d, and **own the `{root.name} #{id}` name rule** (today triplicated — client, [api.py:300](backend/apps/citation/api.py#L300), [extractors.py:279](backend/apps/citation/extractors.py#L279); now 3 → 1). Lift it out of `get_or_create_external_source` ([extractors.py:276-291](backend/apps/citation/extractors.py#L276)) so **both** that patch helper and the interactive path call it. **Two** leaves not one: dedup layers genuinely differ — web reuse is upstream in `recognize_url`, scheme dedup is `get_or_create` in the leaf. (Not the Never trap — recognition _storage_ stays split; only the child _mint_ converges.)
  - **Behavior change — flag it.** `create_citation_source`'s identifier branch plain-creates and **422s on a duplicate**; through the `get_or_create` leaf, re-citing IPDB #1234 **reuses** the existing child — better UX, and it kills the 422-vs-idempotent divergence `get_or_create_external_source`'s docstring laments ([extractors.py:250](backend/apps/citation/extractors.py#L250)). Call it out in the commit.
- **Tests:** `get_or_create_web_source` subdomain-of-seeded-root mints a validated child via `create_web_child`; identifier re-cite reuses via `get_or_create_scheme_child`; both leaves attribute when given a user, leave null otherwise; `get_or_create_external_source` and the interactive path produce the same scheme child through the one leaf.

🛑 STOP.

### P1.3 — two child endpoints; `create_citation_source` sheds all child/link logic — `api.py`, `schemas.py`, frontend

**Three** client call sites POST `/api/citation-sources/`, and `create_citation_source` dispatches on input shape (has `url`? has `identifier`?) — the god-endpoint. Give each child kind its own thin endpoint; reduce `create_citation_source` to one job.

- **`POST /api/citation-sources/{parent}/pages/`** `{url, page_name}` → `create_web_child`. Point the explicit-parent "add a page" UI ([CitationWebCreateStage.svelte:149](frontend/src/lib/components/input/citation/CitationWebCreateStage.svelte#L149)) at it (it honors the chosen parent — no re-recognition — which is its whole reason for being separate from `cite-url`).
- **`POST /api/citation-sources/{parent}/records/`** `{identifier}` → `get_or_create_scheme_child`. Point `createChildByIdentifier` ([citation-types.ts:160](frontend/src/lib/components/input/citation/citation-types.ts#L160)) at it. The client sends only `parent_id`/`source_type`/`identifier` — **not `name`**: the leaf owns the name rule now.
- **`create_citation_source` drops `url`/`link_type`/`link_label` and its link-mint + identifier branches.** One job: create a **root** (book/magazine) or a **linkless authored child**; never touches `url`/`homepage`/links/`CitationSourceRootDomain`, no input-shape branching. Dissolves Cleanup C1 (no link mint) and closes the duplicate-display-root vector by construction.
- **`extra="forbid"` on `CitationSourceCreateSchema`** so a stray `url`/`link_type` is a loud **422**, not a pydantic silent-drop no-op.
- **Exhaustive client sweep — `grep` every `POST('/api/citation-sources/'`, don't name one component** (this is the cross-call-site drift that keeps biting). All three sites currently send now-forbidden fields:
  - `CitationCreateStage.svelte:84` (authored root) — drop `link_type`/`link_label`.
  - `CitationWebCreateStage.svelte:149` (web page) — → the `pages/` endpoint.
  - `citation-types.ts:160` `createChildByIdentifier` (scheme child) — → the `records/` endpoint; drop `name`/`link_type`/`link_label`.
    Miss one → it 422s at runtime. Wire-shape change → `make codegen` + frontend recheck.
- **Tests:** the `pages/` endpoint mints a web child (validated + attributed); the `records/` endpoint mints/reuses a scheme child; `create_citation_source` with `url`/`link_type` → 422 (`extra="forbid"`); authored root (no `url`) still works; **rework `test_api.py:544`'s parentless-`url` coverage** ([test_api.py:544](backend/apps/citation/tests/test_api.py#L544), `test_create_with_url_creates_source_and_link` / `test_create_with_url_and_link_label` + the parentless root-domain-mint tests pin the _removed_ behavior) to assert the 422 + linkless-create reality; keep the authored-root coverage.

🛑 STOP.

### P1.4 — make `normalize_host` idempotent (bug fix, PSL-free) — `hosts.py`

- Strip **all** consecutive leading `www.` labels (`www.www.foo.com` → `foo.com`; `wwworld.example.com` keeps its label). Fixes a real bug: single-strip stored `www.foo.com` and **shadowed** `foo.com`. Update the docstring and the `www.www.example.com` test assertion. No PSL — a standalone bug fix that belongs with the stabilization.
- **Tests:** idempotence (`f(f(x)) == f(x)`, incl. multi-`www`).

🛑 STOP.

## Phase 2 — Domain governance (PSL rounding + `domains:`)

New behavior on the clean foundation. Context #1/#2 are already fixed; this is the anti-fragmentation layer and is the more deferrable phase.

### P2.1 — PSL + host predicates — `hosts.py`

- Add `publicsuffixlist` via **`uv add publicsuffixlist==<pinned>`** (commit `uv.lock`; CI runs `uv sync --frozen`). Per-module `[[tool.mypy.overrides]]`, not a global flag. Renovate/dependabot entry — a snapshot rots.
- `is_public_suffix(host: Host) -> bool` and `registrable_domain(host: Host) -> Host | None` — `Host` in / out. Build `PublicSuffixList` **once at module load** — the single `Any` boundary. **Honor the PRIVATE section** (`github.io` stays a public suffix; `foo.github.io` whole). `accept_unknown=True`.
- `is_dns_host(host: Host) -> bool` — syntactic only: reject IP literals (`ipaddress.ip_address()`; bracket-stripped `::1`); dot-separated labels (1–63 chars, **≥1 dot**, no leading/trailing hyphen, TLD not all-numeric). **Pin the charset ASCII `[a-z0-9-]`**, _not_ `str.isalnum()` — `isalnum()` is unicode-true. ASCII-only accepts punycode, rejects raw-unicode IDN (Known limitations).
- `is_reserved_tld(host: Host) -> bool` — rightmost label in a frozen RFC-6761/6762 set (`localhost`, `invalid`, `test`, `example`, `local`). A standards constant, not a denylist.
- **Tests (no DB):** each helper; the **two-directional `github.io` canary**; the **`registrable_domain(h) is None ⟺ is_public_suffix(h)` equivalence** (the funnel and `clean()` both lean on it — pin against a snapshot bump).

🛑 STOP.

### P2.2 — the funnel + the universal `clean()` predicate — `hosts.py`, `models.py`

- `root_host_from_url(url) -> Host` in `hosts.py`, raising **`HostError(reason)`** (define it here) at each gate — never `HttpError`.
- `CitationSourceRootDomain.clean()` enforces the **universal predicate**: `normalize_host` → `is_dns_host` → `not is_public_suffix` → root-only. **Not** `is_reserved_tld` (funnel-only), **not** rounding.
- **No CHECK constraints, no audit migration** (right-size).
- **Tests:** funnel `s4.american-pinball.com/…` → `american-pinball.com`; `HostError` on IP / `localhost` / `x.localhost` / bare suffix / hostless; `clean()` rejects an IP and a bare suffix on direct `full_clean`, accepts a verbatim subdomain (`twip.kineticist.com`) and a reserved-TLD host (declare is trusted).

🛑 STOP.

### P2.3 — `cite-url` derives its root via the funnel — `api.py`

- `cite-url`'s no-match branch: `try: host = root_host_from_url(url) except HostError → HttpError(422, …)`, at the **top**, before any write; synthesize `https://{host}/`; mint the `CitationSourceRootDomain` at `host`; `create_web_child` under it (already the P1.2 leaf). Savepoint host-unique race unchanged. This is the funnel's only caller.
- **Migrate the `cite-url` rooting tests off `.example`** (the funnel `HostError`s reserved TLDs) → real registrable domains. Declare-path / `recognize_url` `.example` fixtures don't hit the funnel and stay.
- **Tests:** no-match rounds `s4.american-pinball.com/…` → `american-pinball.com` root (assert `CitationSourceRootDomain.host` **and** synthesized `homepage.url == "https://american-pinball.com/"`); 422 on IP/reserved/bare-suffix before any write.

🛑 STOP.

### P2.4 — declare: the `domains:` verb (a diff, not a rebuild) — `seeding.py`

Most exists: `_roots_owning_hosts`, `_ensure_root_domains`, `ensure_root_source` ([seeding.py:177-228](backend/apps/citation/seeding.py#L177)) already do verbatim-host minting and exact-host dedup. New work is narrow:

- **Parse `domains: [h, …]`** off the patch node; add it to `SeedSource`; validate (list of host strings).
- **Union with the declared homepage host** into the existing `_ensure_root_domains(source, hosts, …)` — `hosts = _declared_homepage_hosts(links) ∪ normalize_host(each domains entry)`. One row per distinct host; existing dedup + warn-skip reused unchanged.
- No rounding (declare). `homepage:` stays display-only-plus-its-host; `domains:` adds hosts for multi-host roots (rebrand, `.com`+`.co.uk`, asset host) — replacing v1's "second homepage link" hack.
- **Scope note:** `domains:` goes _beyond_ the three Context problems (Known-limitation #1, multi-host roots) — **splittable to its own follow-up** if you want Phase 2's `cite-url` rounding to land alone first.
- **Tests:** `domains:` adds verbatim hosts (incl. subdomain — no round); `homepage:` + `domains:` union; re-declare a root by name with a new `domains:` host → adds row, no duplicate; dedup-by-exact-host; hosts spanning two roots → warn + skip, no `IntegrityError`.

🛑 STOP.

## Cleanup — `link_type` hygiene (orthogonal, land anytime)

- **~~C1 — `link_type` default footgun~~ — dissolved by P1.3.** Once `create_citation_source` drops `url`/`link_type` it mints no link, so it can't produce a mistyped child `homepage` link. Source gone; historical rows are C3.
- **C2 — enum-type the remaining `link_type` schema fields** (`CitationSourceLinkSchema` output, `CitationSourceLinkCreateSchema`, `CitationSourceLinkUpdateSchema` — three, since P1.3 removed the create schema's field) as `LinkType` `TextChoices`. Validation at the Pydantic boundary; DB CHECK stays as backstop. `make codegen`, recheck frontend. Test bare-value serialization (`"homepage"`, not `"LinkType.HOMEPAGE"`).
- **C3 — reclassify the 145 child `homepage` links → `reference`** (plain `UPDATE` migration; not claim-controlled). Optional cosmetic.

🛑 STOP.

## Verification

```bash
cd backend && uv run pytest apps/citation -q
uv run python manage.py migrate
uv run python manage.py shell -c "from apps.citation.extractors import recognize_url; print(recognize_url('http://s4.american-pinball.com/games/gtf/docs/manual.pdf'))"
# → Recognition(parent_name='American Pinball', ...)
make mypy && make quality   # quality = lint + codegen + frontend svelte-check (C2 changes generated API types)
uv sync --frozen
```

- **Dev rebuild** (verifies patches + the new `clean()` predicate end-to-end): reset the dev DB to `backend/db.pre-0009.sqlite3`, `migrate`, re-apply patches (`make ingest-patches`) — this re-runs every patch through `clean()`, so any pre-existing non-DNS / public-suffix host surfaces here. Confirm the TWiP root recognizes `twip.kineticist.com` verbatim. Prod stays at patch `0038-model-game-formats`; nothing here requires advancing it, and no patch needs rewriting.
- **Before deploy:** since there's no audit migration, spot-check prod's existing `CitationSourceRootDomain.host` values are all DNS-valid and non-public-suffix (a one-line shell query) — the dev rebuild covers patch-seeded rows, this covers anything else.

## Known limitations

- **Asset hosts on a different registrable domain** (a third-party CDN, a host outside the publisher's domain) won't match — longest-suffix only collapses within one registrable domain. Add a `domains:` row (or admin-inline domain).
- **Non-PSL "subdomain-per-publisher" platforms** collapse to one shared registrable-domain root under `cite-url` rounding until a curator splits them with `domains:` rows.
- **A genuinely-unknown real gTLD** rounds via `accept_unknown=True` rather than 422-ing — accepted fail-open; the renovate bump keeps the snapshot current.
- **Raw-unicode IDN hosts are rejected** (`is_dns_host` is ASCII-only) — an internationalized recognition host must be punycode (`xn--…`). Revisit (`idna` in `normalize_host`) only if a real publisher needs it.

## Deferred

- **Admin "promote a subdomain into its own root" gardening tool** — creates a more-specific root and reparents the children that route to it. Orthogonal to _declaring_ a host; this is _reparenting_ at gardening time. Until then, creating a more-specific root leaves existing children under the ancestor (a temporary split).
- **Route the patch citation dispatch through `recognize_url` + the leaves.** The patch side splits web-vs-scheme up front by `if ref.url` ([persist.py:242-245](backend/apps/claim_ingest/apply/persist.py#L242)) — two entry points — while the interactive side lets a single `recognize_url` call dispatch. After P1.2 both kinds mint through shared leaves, so the patch dispatch _could_ collapse onto `recognize_url` + the leaves too, making the surfaces fully symmetric (one resolver, two surfaces). Bigger blast radius than the scheme-leaf, same grain; deferred, not lost.

## Never

- **Delete + reparent on delete** — a source with children is never deletable (`on_delete=PROTECT`).
- **Auto-reparent on save** — regrouping is deliberate gardening.
- **Fold TWiP into Kineticist** — TWiP stays its own publication (`domains: [twip.kineticist.com]` or its `homepage:` host).
- **Unify scheme- and host-recognition _storage_** — a scheme root recognizes via `identifier_key` (one value, extractor-regex match); a web root via `CitationSourceRootDomain` host (many values, suffix match). They look like one "recognition identity" concept but have different cardinality and match algorithms. `recognize_url` already unifies them at the _read_ point — the only place unification pays. Merging the storage is the "looks similar, isn't" over-abstraction that bred the original link→recognition mess. Leave them separate.
