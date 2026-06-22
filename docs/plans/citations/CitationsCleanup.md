# Plan: citation write-layer cleanup

The get-well work for the citation **write layer** — the source-side minting paths, the recognizer and the type-dispatch — before any further behavior rides on them. Lands commit-by-commit on a **fresh branch off `main`**, opened after [WebCitationDomainDisablement.md](WebCitationDomainDisablement.md) ships the current branch. Each commit is the review boundary (no PR-level review), so each is sized to be reviewed and reasoned about on its own, and is behavior-preserving unless a change is flagged.

## Context

This plan is the execution form of [CitationWriteLayerDebt.md](CitationWriteLayerDebt.md) §4 (the source-type-dispatch + `recognize_url` tidy, which rebuilds the narrower "Phase 1" of [WebCitationDomains2.md](WebCitationDomains2.md) around a model-driven spine — §4 sketches a `CitationSourceTypeStrategy`; C3 lands the data-only trait table that fits, see [§ Why not a strategy](#why-a-trait-table-not-a-strategy)) folding in that plan's P1.2/P1.3/P1.4. It supersedes WebCitationDomains2's Phase 1. Subdomain matching's _enablement_, its PSL public-suffix guard, the funnel rounding and the `domains:` verb are in [CitationDomainGovernance.md](CitationDomainGovernance.md); **exact** host matching already shipped via [WebCitationDomainDisablement.md](WebCitationDomainDisablement.md). Neither is in scope here.

## Why this scope, and only this scope

The full-system citation audit ([CitationSystemAudit.md](CitationSystemAudit.md)) found the costly, migration-forcing debt concentrated on `CitationInstance` (access-URL tier, the quote field, the attachment reshape). All of that is **deferred** — see [Out of scope](#out-of-scope). This cleanup is the **source side** only: `CitationSource` / `CitationSourceLink` / `CitationSourceRootDomain` minting, `recognize_url`, and the type branching in shared code. It touches `CitationInstance` nowhere, so it is independent of every deferred item.

The web-citation feature and exact-host recognition already shipped (WebCitationDomainDisablement.md). This cleanup is a **behavior-preserving refactor on a fresh branch** — nothing user-facing. **Merge = deploy to prod**, so it must stay coherent and shippable at every point; the deliberate behavior changes below are gated by the dev rebuild, not by a release flag.

**Subdomain matching stays disabled here.** The disablement branch shipped exact matching with the longest-suffix helpers (`label_suffixes`/`longest_suffix_match`) built but dormant; this cleanup runs on that foundation and leaves them dormant. [CitationDomainGovernance.md](CitationDomainGovernance.md) re-enables them with the public-suffix guard that makes them safe.

## Decisions

- **C6's patch-dispatch unification is a splittable tail.** The `recognize_url` tidy lands in C6 regardless. Routing the patch `if ref.url` dispatch through the shared resolver (making `CitationRef` a sum type) is the bigger blast radius; it rides C6 if it stays cheap, and splits to its own commit if it balloons. Neither blocks the rest.
- **This cleanup is a fresh branch off post-ship `main`; merging it deploys the behavior-preserving get-well at low risk.** Subdomain matching + its guard, `access_url`, the rest of domain governance and the attachment reshape each follow as their own branches.
- **We pave `access_url`, we do not build it.** Paving is free and already in the plan: C6's ordered-list recognizer is the insertion point for archive-peeling and CitationUrlModel's normalized identity-URL table; C4's `create_web_child` is the one validated child home. `access_url`'s actual column lives on `CitationInstance` (the cite-time _instance_ path, which this source-side cleanup never touches), so it is a clean separate migration later — building the identity-URL table (child dedup, D10/D11) is part of _that_ work, not this.

## The two ideas this plan installs

1. **One name for the root/child distinction, then one trait table per source type.** The root-vs-child rule is re-spelled across app code; the `source_type == "web"` branch recurs in shared code (`skip_locator`, `is_abstract`, the web-flatness rule). CLAUDE.md flags exactly this ("branch on type in shared code") as the smell that should trigger a model-driven pattern. We give the distinction a name (`is_root`, `roots()`/`children()`) and pull the per-type facts into one source-type trait table, so the next type's flatness/abstractness/locator _behavior_ is a trait row, not three new `if source_type` branches scattered through shared code. (A new type is still a model change — a `SourceType` member, the `source_type`/`identifier_key` CHECK migrations, schemas + codegen; the table narrows the behavioral branching, not that.)
2. **Two validated child-minting leaves, behind thin endpoints, fed by one tidied recognizer.** Web- and scheme-child creation converge onto two `full_clean`-validated helpers (closing the one real `clean()` bypass on the patch path); the god-endpoint splits into per-kind endpoints; the 3-step `recognize_url` pipeline becomes an ordered recognizer list that both the interactive and patch surfaces route through.

Recognition stays **off** the trait table — it runs before the type is known, is keyed by input kind, and is already its own registry (`EXTRACTORS`). Folding it onto the type would relapse into the link→recognition conflation. See CitationWriteLayerDebt §4 for the full argument.

## The commit sequence

Dependency-ordered. 🛑 STOP after each for review before committing. Commit messages: no ephemera.

### ✅ DONE: C1 — make `normalize_host` idempotent (standalone bug fix) — `hosts.py`

WebCitationDomains2 P1.4. Smallest, fully independent — a good first landing.

- Strip **all** consecutive leading `www.` labels ([hosts.py:34](backend/apps/citation/hosts.py#L34)): `www.www.foo.com` → `foo.com`; `wwworld.example.com` keeps its label. Today's single strip yields `www.foo.com`, which then **shadows** `foo.com`. PSL-free.
- Update the docstring and the `www.www.example.com` test assertion.
- **Audit stored hosts before merge.** `host` is `unique` and stored normalized ([models.py:390](backend/apps/citation/models.py#L390)); the old single-strip could have _stored_ `www.foo.com` from a `www.www.foo.com` write, and this change would orphan such a row from recognition (the URL now normalizes to `foo.com`). Confirm `CitationSourceRootDomain.objects.filter(host__startswith="www.")` is empty in the dev rebuild — almost certainly zero rows (a `www.`-prefixed recognition host is pathological), but "merge = deploy to prod" + a behavior-preservation claim warrants the check. A nonempty result means a re-normalize data migration rides this commit, not just a code change.
- **Tests:** idempotence (`f(f(x)) == f(x)`, including multi-`www`).

🛑 STOP.

### ✅ DONE: C2 — name the root/child distinction — `models.py`, app-wide

WebCitationDomains2 P1.1. Pure refactor, behavior-preserving. Lands before the trait table because C3's reads and the D2 guard sit on the named distinction.

- `CitationSourceQuerySet.roots()` / `.children()` (on a manager) — replace the **direct** `CitationSource.objects.filter(parent__isnull=…)` sites: [extractors.py:142](backend/apps/citation/extractors.py#L142), [extractors.py:262](backend/apps/citation/extractors.py#L262), [seeding.py:125](backend/apps/citation/seeding.py#L125).
- `CitationSource.is_root` property (`parent_id is None`) — replace every instance-level `parent_id is None` / `is not None`: [models.py:257](backend/apps/citation/models.py#L257), [models.py:277](backend/apps/citation/models.py#L277), [api.py:163](backend/apps/citation/api.py#L163), [admin.py:57](backend/apps/citation/admin.py#L57). (Not [api.py:281](backend/apps/citation/api.py#L281) — that tests an _input_ `data.parent_id`, not a source's rootness.)
- **The cross-FK lookups stay raw.** `source__parent__isnull=True` on `CitationSourceRootDomain` ([extractors.py:212](backend/apps/citation/extractors.py#L212), [seeding.py:192](backend/apps/citation/seeding.py#L192)) and `citation_source__parent__isnull=False` on `CitationSourceLink` ([extractors.py:175](backend/apps/citation/extractors.py#L175), [extractors.py:341](backend/apps/citation/extractors.py#L341)) traverse a FK on a _different_ model's queryset — a `CitationSourceQuerySet` method can't express them. Leave them; they're defense-in-depth filters, not the rootness predicate the manager names.
- **Leave the CHECK-constraint `Q()` conditions as-is** — a manager method can't appear in a constraint. App-code re-spellings only.

🛑 STOP.

### ✅ DONE: C3 — source-type trait table + web-flatness guard — `models.py`, new `source_type_traits.py`

CitationWriteLayerDebt §4. A `dict[SourceType, SourceTypeTraits]` — one frozen-dataclass record per type, **data only, no behavior** — with an import-time exhaustiveness assert. This is CLAUDE.md's "typed spec" rung: the facts that vary by source type live in one type-keyed lookup the model reads from, killing the `source_type == "web"` branches in shared code. **No `create_child` here** — child _creation_ keys on parent kind (scheme root vs domain root), not source type (both leaves mint `SourceType.WEB` children), so it stays as the two plain leaves in C4, not a method on this table. See [§ Why not a strategy](#why-a-trait-table-not-a-strategy). Pure refactor + one flagged guard.

- **File shape — a dependency-free leaf, like `hosts.py`.** `source_type_traits.py` **owns `SourceType`** (lifted out of the `CitationSource` body), plus `SourceTypeTraits` and the registry; `models.py` imports all three one-way and re-aliases `CitationSource.SourceType = SourceType` so every existing `CitationSource.SourceType.WEB` reference (6 sites, all in `models.py`/`extractors.py`/`api.py`) keeps working unchanged. This avoids the cycle the naive shape creates: a registry keyed by `CitationSource.SourceType` _inside_ `models.py` while `models.py` reads the registry is a mutual module-load import. The enum move is a no-op for the DB (`choices` values unchanged) — **verify `makemigrations` reports no change**.
- `SourceTypeTraits(flat_hierarchy, parentless_abstract, child_skips_locator)` — web `(True, True, True)`, magazine `(False, True, False)`, book `(False, False, False)`. Exhaustiveness gate: a `_assert_exhaustive_traits(registry)` helper checking `registry.keys() == set(SourceType)`, called once at import so a new enum member without a row fails at load, not at runtime. A **helper, not a bare module-level `assert`**, so the test calls it directly against a deliberately-incomplete dict — no `importlib.reload`.
- **One typed accessor, no raw indexing.** `source_type_traits(source_type: str | SourceType) -> SourceTypeTraits` coerces `SourceType(source_type)` before indexing. `source.source_type` is a `CharField` (types as `str`, and str-Enum key identity is version-fragile), so callers go through the accessor — it's the single typed chokepoint and validates the value (bad string → `ValueError`, not a silent miss). Never index `SOURCE_TYPE_TRAITS` with a bare model field.
- Re-point `skip_locator` ([models.py:255](backend/apps/citation/models.py#L255)) and `is_abstract` ([models.py:259](backend/apps/citation/models.py#L259)) at `source_type_traits(self.source_type)`; `ABSTRACT_PARENTLESS_SOURCE_TYPES` ([models.py:252](backend/apps/citation/models.py#L252)) dissolves into `parentless_abstract`.
- **Add the D2 web-flatness guard** in `clean()`: a `flat_hierarchy` type's child must have a **root** parent (no web grandchildren). **Flagged change** — rejects a previously-DB-valid-but-recognition-broken web grandchild; nothing creates one today, so no existing row is affected (confirm in the dev rebuild).
- Keep it **data-only** — three facts, no methods. Each trait earns its row from a real `if source_type` in shared code today; none speculative.
- **Tests:** each trait per type via the accessor; the accessor rejects a bogus value; `_assert_exhaustive_traits` raises on a dict missing a type; the D2 guard rejects a web child whose parent is itself a web child, accepts the book `root → edition → page` nesting unchanged.

#### Why a trait table, not a strategy

The model-driven move here is to give per-type **facts** one type-keyed home, not to add per-type **behavior**. A strategy (an ABC with a `create_child` method per `SourceType`) would over-claim: both child leaves mint `SourceType.WEB` children, and the real fork between them is `parent.identifier_key` (scheme root) vs. a recognition domain (web root) — not the source type. A `SourceType`-keyed `create_child` would just re-branch on parent kind internally, putting the `if` right back, and would be the one speculative member on an otherwise data-only object. So the facts go in the trait table and the two leaves stay plain functions dispatched by the scheme-vs-domain resolver `recognize_url` already encodes. A future type with genuinely per-type _behavior_ (not just facts) escalates to a strategy then; the trait table is the smallest pattern that fits today's 3×3.

🛑 STOP.

### C4 — two validated child leaves — `api.py`, `extractors.py`

WebCitationDomains2 P1.2. Converge web- and scheme-child minting onto two `full_clean`-validated leaves, dispatched by parent kind (scheme root → scheme leaf; else web leaf) — the fork `recognize_url` already draws, not a `source_type` switch. Closes D4 (the one real `clean()` bypass). **Two flagged behavior changes.**

- **`create_web_child(parent, url, name="", *, created_by=None)`** — child `CitationSource` + `reference` link, both `full_clean`d. Replace `_create_web_child` ([api.py:357](backend/apps/citation/api.py#L357)) and `get_or_create_web_source`'s inline `.objects.create` ([extractors.py:296](backend/apps/citation/extractors.py#L296)).
  - **Attribution:** `created_by is None` → leave `created_by`/`updated_by` null (not a system user) — preserves ingest semantics (patch children tie to the `ingest_run`). Interactive passes `request.user`; patch passes nothing.
  - **Flagged change:** `URLField` format validates only in `full_clean`, so the patch path can now reject a malformed historical URL that `.objects.create` tolerated. **The dev rebuild is the gate** — fix the offending URL in its patch.
  - **Error contract inside ingest.** The leaf runs inside `apply_plan`'s transaction via `get_or_create_web_source` → [`_resolve_cite_source_id`](backend/apps/claim_ingest/apply/persist.py#L242), which today only expects `CitationSource.DoesNotExist` / `ValueError`. A new `full_clean` `ValidationError` must surface as a patch-scoped failure (file + cite handle), not an unhandled traceback that aborts the run uninformatively. Decide where it's caught — wrap at the leaf into the same error type the scheme path already raises, or catch at the resolver — so the dev rebuild reports _which_ patch URL is bad, not just that something threw. Make this explicit; don't let the dev rebuild "surface" it as a raw crash.
- **`get_or_create_scheme_child(root, identifier, *, created_by=None)`** — `get_or_create` the `(root, identifier)` child + `reference` link, `full_clean`d, owning the `{root.name} #{id}` name rule (today triplicated — client, [api.py](backend/apps/citation/api.py), [extractors.py](backend/apps/citation/extractors.py); now 3 → 1). Lift out of `get_or_create_external_source` ([extractors.py:242](backend/apps/citation/extractors.py#L242)) so both it and the interactive path call the one leaf. **Two leaves, not one:** dedup layers genuinely differ — web reuse is upstream in `recognize_url`, scheme dedup is `get_or_create` in the leaf. (Recognition _storage_ stays split; only the child _mint_ converges.)
  - **Flagged change:** the interactive identifier branch plain-creates and 422s on a duplicate; through `get_or_create` it now **reuses** the existing child (better UX, kills the 422-vs-idempotent divergence).
- **Tests:** a cite that exact-matches a seeded root mints a validated child via `create_web_child`; identifier re-cite reuses via `get_or_create_scheme_child`; both leaves attribute when given a user, leave null otherwise; the patch helper and the interactive path produce the same scheme child through the one leaf.

🛑 STOP.

### C5 — two child endpoints; `create_citation_source` sheds web/scheme — `api.py`, `schemas.py`, frontend

WebCitationDomains2 P1.3. The most user-facing commit (wire-shape change + the heaviest test churn, D22). Three client call sites POST `/api/citation-sources/` into the god-endpoint; give each child kind its own thin endpoint and reduce `create_citation_source` to one job.

- **`POST /api/citation-sources/{parent}/pages/`** `{url, page_name}` → `create_web_child`. Point the explicit-parent "add a page" UI ([CitationWebCreateStage.svelte](frontend/src/lib/components/input/citation/CitationWebCreateStage.svelte)) at it — it honors the chosen parent, no re-recognition.
- **`POST /api/citation-sources/{parent}/records/`** `{identifier}` → `get_or_create_scheme_child`. Point `createChildByIdentifier` ([citation-types.ts](frontend/src/lib/components/input/citation/citation-types.ts)) at it; the client sends `parent_id`/`source_type`/`identifier`, **not `name`** (the leaf owns the name rule).
- **`create_citation_source` drops `url`/`link_type`/`link_label` and its link-mint + identifier branches.** One job: create a **root** (book/magazine) or a **linkless authored child**. Never touches `url`/`homepage`/links/`CitationSourceRootDomain`, no input-shape branching. Dissolves the `link_type`-default footgun by construction.
- **`extra="forbid"` on `CitationSourceCreateSchema`** — a stray `url`/`link_type` is a loud 422, not a silent pydantic drop.
- **Exhaustive client sweep** — `grep` every `POST('/api/citation-sources/'`, don't name one component (this is the cross-call-site drift that keeps biting). All three sites send now-forbidden fields. Miss one → runtime 422. Wire-shape change → `make codegen` + frontend recheck.
- **Tests:** `pages/` mints a validated, attributed web child; `records/` mints/reuses a scheme child; `create_citation_source` with `url`/`link_type` → 422; authored root (no `url`) still works; **rework `test_api.py`'s parentless-`url` coverage** (it pins the removed behavior) to assert the 422 + linkless-create reality; keep the authored-root coverage.

🛑 STOP.

### C6 — tidy `recognize_url`; (splittable) route the patch dispatch through it — `extractors.py`, `persist.py`, `plan.py`

CitationWriteLayerDebt §4, the spine. The 3-step pipeline ([extractors.py:119](backend/apps/citation/extractors.py#L119)) is already a hardcoded sequence; tidy it into an ordered list of recognizers over the existing `EXTRACTORS` + host machinery. Step 3 is the exact-host recognizer (shipped in WebCitationDomainDisablement.md); the future suffix recognizer becomes one more list entry. A new mechanism (DOI, archive.org id) likewise. Behavior-preserving.

- **Tidy (in scope):** ordered recognizer list, same resolution order (scheme extractor → exact child-link → exact host), no behavior change.
- **Patch-dispatch unification (splittable tail — see Decisions):** make `CitationRef` ([plan.py:44](backend/apps/claim_ingest/plan.py#L44)) a real **sum type** (web form vs scheme form as distinct types) so "exactly one form is set" is enforced by construction, and route `_resolve_cite_source_id`'s `if ref.url` ([persist.py:242](backend/apps/claim_ingest/apply/persist.py#L242)) through the shared resolver + the C4 leaves. Collapses the double-spelled web/scheme dispatch (D3/D20), making the two surfaces symmetric (one resolver, two surfaces). If this balloons, split it to its own commit; the tidy stands alone.
- **Tests:** `recognize_url` resolves scheme / exact-child / exact-host cases identically to before; (if the tail lands) a neither-set or both-set `CitationRef` is unconstructable; the patch path and the interactive path resolve the same URL to the same source through the shared resolver.

🛑 STOP.

## Debt reach

Which inventory items from [CitationWriteLayerDebt.md](CitationWriteLayerDebt.md) each commit closes. ✅ fixes · ⚙️ consolidates · 🏠 localizes (future fix gets one home).

| Commit | Closes                                | Notes                                                                                                                 |
| ------ | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| C1     | D8 ✅                                 | `normalize_host` idempotence                                                                                          |
| C2     | (foundation)                          | names the root/child distinction the rest reads from                                                                  |
| C3     | D2 ✅, D11/D19 🏠                     | web-flatness guard; `parentless_abstract`/`skip_locator` become trait reads; abstract-root rejection gets a data home |
| C4     | D4 ✅, D15 ✅, D7 ⚙️                  | closes the `.objects.create` bypass; one scheme-child name rule; recognition-host mint consolidating                  |
| C5     | D12 ✅, D13 ✅, D14 ✅                | god-endpoint split; `extra="forbid"`; `link_type` footgun dissolved                                                   |
| C6     | D3/D20 ✅ (if tail lands), D10/D11 🏠 | one resolver, two surfaces; child-URL canonicalization gets a single future home                                      |

**Untouched by design** (orthogonal, deferred): D5/D6 (attribution), D9 (declare-path link-type coupling — stays off the type), D16–D18 (the extract surface), D21/D22 (instance mint, test churn — C5 absorbs the churn).

## Out of scope

Deferred, each its own later work. None blocks or is blocked by this cleanup.

- **Subdomain (longest-suffix) matching + its PSL public-suffix guard + the funnel rounding + the `domains:` verb** → [CitationDomainGovernance.md](CitationDomainGovernance.md). Exact matching shipped via [WebCitationDomainDisablement.md](WebCitationDomainDisablement.md); the governance follow-up enables suffix matching with the guard that makes it safe, then layers rounding/`domains:` on top.
- **`access_url` on `CitationInstance`** (CitationUrlModel v1) — additive, non-conflicting; likely the next work after this.
- **The attachment reshape + quote field** (CitationModelUnification — changeset FK, de-fan-out of `_attach_citation`, retire `Claim.citation`, the `quote` column) — the `CitationInstance` migration cluster. Separable into attachment-vs-quote; both deferred.
- **Archive-URL peeling** in `recognize_url` (CitationUrlModel) — unbuilt; see [CitationSystemAudit.md](CitationSystemAudit.md) EX1.
- **Child-URL fragmentation** (D10/D11) — near-duplicate URLs minting duplicate children, nondeterministic `.first()`. C6's recognizer is the future home; not fixed here.
- **Attribution on ingest writes** (D5/D6) and the **extract surface** (the three overlapping schemas, the pickled `extract:v2:*` cache, the recognize-twice TOCTOU — D16/D17/D18).

## Verification

```bash
cd backend && uv run pytest apps/citation apps/claim_ingest apps/claim_edit -q
uv run python manage.py shell -c "from apps.citation.extractors import recognize_url; print(recognize_url('https://twip.kineticist.com/'))"
# exact-host recognition → resolves the seeded TWiP/Kineticist root
make mypy && make quality   # quality = lint + codegen + svelte-check (C5 changes generated API types)
```

- **Dev rebuild** gates the flagged guards end-to-end: reset the dev DB, `migrate`, re-apply patches (`make ingest-patches`) — this re-runs every patch through the new `full_clean` leaves (C4) and the C3 D2 guard, so any pre-existing malformed URL or web grandchild surfaces here. Fix it in its patch. (Exact matching and the 0073 handling already landed via WebCitationDomainDisablement.md, so the rebuild is green going in.)
- **Before merge** (= deploy): the suite green, the dev rebuild clean, the frontend rechecked after C5's wire-shape change.
