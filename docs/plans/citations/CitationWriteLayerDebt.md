# Citation write-layer debt inventory

A full-picture audit of every path that writes `CitationSource` / `CitationSourceLink` / `CitationSourceRootDomain` / `CitationInstance`, the debt each carries and whether `WebCitationDomains3.md` (the plan) addresses it. Goal: decide whether the foundation is stable enough to build domain governance on, or whether the get-well work needs to be bigger than Phase 1.

## 1. The write surface (the full picture)

Four front doors, one shared read path. They mint the same three row types with **inconsistent discipline**.

| #           | Writer                                                                                                                                           | Mints                                                          | Validates (`full_clean`)                                | Attributes             | Re-recognizes                |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- | ------------------------------------------------------- | ---------------------- | ---------------------------- |
| Interactive |                                                                                                                                                  |                                                                |                                                         |                        |                              |
| 1           | `create_citation_source` ([api.py:275](../../../backend/apps/citation/api.py#L275))                                                              | root \| child \| scheme-child + link + recognition-domain      | ✅ (`_clean_and_save`)                                  | ✅ user                | ❌ trusts client `parent_id` |
| 2           | `cite_url` ([api.py:445](../../../backend/apps/citation/api.py#L445))                                                                            | web child (+ root)                                             | ✅                                                      | ✅ user                | ✅ `recognize_url`           |
| 3           | `_create_web_child` ([api.py:357](../../../backend/apps/citation/api.py#L357))                                                                   | child + reference link                                         | ✅                                                      | ✅ user                | n/a                          |
| 4           | `_create_root_and_child` ([api.py:384](../../../backend/apps/citation/api.py#L384))                                                              | root + homepage link + recognition-domain                      | ✅ (domain via `validate_unique=False` + bare `save()`) | ✅ user                | savepoint race re-recognize  |
| 5           | `update_citation_source` / `_link` ([api.py:597](../../../backend/apps/citation/api.py#L597), [659](../../../backend/apps/citation/api.py#L659)) | edits source / link                                            | ✅                                                      | ✅ user                | n/a                          |
| Patch       |                                                                                                                                                  |                                                                |                                                         |                        |                              |
| 6           | `ensure_root_source` ([seeding.py:269](../../../backend/apps/citation/seeding.py#L269)) → `_create_source`/`_create_link`/`_ensure_root_domains` | root + links + recognition-domains (declare, verbatim)         | ✅                                                      | ❌ **null**            | n/a (exact-host dedup)       |
| 7           | `get_or_create_web_source` ([extractors.py:296](../../../backend/apps/citation/extractors.py#L296))                                              | web child + reference link                                     | ❌ **`.objects.create`**                                | ❌ **null**            | ✅ `recognize_url`           |
| 8           | `get_or_create_external_source` ([extractors.py:242](../../../backend/apps/citation/extractors.py#L242))                                         | scheme child + reference link                                  | ❌ **`.objects.create` / `get_or_create`**              | ❌ **null**            | extractor only               |
| 9           | `_resolve_cite_source_id` ([persist.py:225](../../../backend/apps/claim_ingest/apply/persist.py#L225))                                           | dispatches 7 vs 8 on `if ref.url`                              | —                                                       | —                      | —                            |
| Admin       |                                                                                                                                                  |                                                                |                                                         |                        |                              |
| 10          | `CitationSourceAdmin` ([admin.py:72](../../../backend/apps/citation/admin.py#L72))                                                               | root/child + link + domain inlines                             | ✅ (ModelForm)                                          | ✅ user (domain: none) | n/a                          |
| Read        |                                                                                                                                                  |                                                                |                                                         |                        |                              |
| —           | `recognize_url` ([extractors.py:119](../../../backend/apps/citation/extractors.py#L119))                                                         | — (3-step: extractor → exact child-link → longest-suffix host) | —                                                       | —                      | the shared resolver          |

The plan's keystone claim — "`recognize_url` is already shared" — is true for the **read**. The **write** is not shared: rows 2/3/4 (interactive) and 7/8 (patch) are parallel re-implementations of the same "resolve → mint child / mint root" dance, with different validation, attribution and dedup. Phase 1 (P1.2) converges the _child mint_ (rows 3+7 → `create_web_child`, the scheme half of 8 → `get_or_create_scheme_child`). Everything else stays split.

## 2. Debt inventory

Severity: 🔴 foundation · 🟠 bites now · 🟡 latent · 🟢 cosmetic.
Plan: ✅ fixed · 🔶 partial · ⏸ deferred · ❌ untouched.

### Foundation / structural

- **D2 🟡 ❌ — Hierarchy depth is a per-`source_type` invariant that nothing enforces.** Depth is not uniform across types, and the rule lives only in contributors' heads:
  - **Web is 2-level, and that flatness is load-bearing.** For a web source the _root_ is special — it alone owns the `CitationSourceRootDomain` recognition rows and `identifier_key`; children are flat leaf pages. Every web write mints a child directly under the matched **root**: `get_or_create_web_source` sets `parent_id=recognition.parent_id` (step 3 is root-only, [extractors.py:211](../../../backend/apps/citation/extractors.py#L211)), and `_create_web_child` is always handed a root id. So nothing _creates_ a web grandchild today — but nothing _forbids_ one. The generic `create_citation_source` ([api.py:281](../../../backend/apps/citation/api.py#L281)), and the planned `pages/` endpoint that "honors the chosen parent — no re-recognition" ([WebCitationDomains3.md](WebCitationDomains3.md) §P1.3), would both accept a `parent_id` pointing at a web _child_, producing a DB-valid web grandchild that's semantically broken for recognition. **The real seam is a _web_ grandchild, not any grandchild** — because web is the one type whose flatness the recognition layer silently assumes.
  - **Book / magazine are genuinely N-level by design** ([Citations.md:27](../../../docs/Citations.md#L27): `work → edition`, `publication → issue → article`; canonical book case `root book → edition → French-language edition → cited page`). This is handled correctly: the code keys on `parent__isnull` / `has_children`, not "child = leaf" — `is_abstract` ([models.py:259](../../../backend/apps/citation/models.py#L259)) flags any node-with-children abstract at any depth, and a middle edition is never the cite target.
  - **The model expresses neither rule.** One self-FK, and the only structural guard is `parent_not_self` ([models.py:174](../../../backend/apps/citation/models.py#L174)) — which blocks only the 1-cycle A→A, not a 2-edit cycle A→B→A. A `web`-only "child's parent must be a root" check (in `clean()` or the cite/pages paths) would make the load-bearing flatness real; a global depth guard would be _wrong_ (it'd break the book case).
- **D3 🔴 ✅ (now Phase 1) — `CitationRef` is a 4-field bag with type-unenforced "two mutually-exclusive forms."** `scheme`/`identifier`/`url`/`archive_url` all default `""` ([plan.py:43](../../../backend/apps/claim_ingest/plan.py#L43)); "exactly one form is set" is a parse-site convention, not a type. The apply-time discriminator is `if ref.url` ([persist.py:242](../../../backend/apps/claim_ingest/apply/persist.py#L242)) — a neither-set or both-set ref isn't caught by the type system, only by trusting `parsing.py`. The web/scheme split is spelled **twice** (parse: [parsing.py:688](../../../backend/apps/claim_ingest/patches/parsing.py#L688); apply: [persist.py:242](../../../backend/apps/claim_ingest/apply/persist.py#L242)) and must stay in sync by hand. **The patch dispatch seam the user flagged. Decision: pulled into Phase 1** (was deferred by the plan) — make `CitationRef` a real sum type (web form vs scheme form as distinct types), so "exactly one form" is enforced by construction and the discriminator is single-spelled. Same grain as the scheme-leaf already in P1.2.

### Validation / attribution

- **D4 🟠 ✅ — The one real `clean()` bypass: patch child mint.** `get_or_create_web_source` ([extractors.py:365](../../../backend/apps/citation/extractors.py#L365)) and `get_or_create_external_source` ([extractors.py:288](../../../backend/apps/citation/extractors.py#L288)) use `.objects.create` — no `full_clean`, so `URLField` format and `validate_no_mojibake` never run on the patch path. The "universal `clean()`" claim is aspirational until P1.2 routes both through validated leaves. (Flagged behavior change: can newly reject marginal historical URLs.)
- **D5 🟡 ❌ — Patch-created sources/links/domains are wholly unattributed.** Rows 6/7/8 leave `created_by`/`updated_by` null and — since sources aren't claims-controlled — have _no_ changeset either. A citation source minted during ingest has zero provenance. The plan **preserves** this ("ingest semantics: null"). Defensible, but means "who added this source" is unanswerable for all ingested data.
- **D6 🟢 ❌ — `CitationSourceRootDomain` has no attribution at all.** No `created_by`/`updated_by` columns ([models.py:360](../../../backend/apps/citation/models.py#L360); admin notes it [admin.py:104](../../../backend/apps/citation/admin.py#L104)). The recognition signal — the thing this whole effort is about — is unattributable on every path.

### Recognition-host minting (the feature's core)

- **D7 🟠 🔶 — Recognition-host mint is triplicated with divergent semantics.** Three writers, three behaviors:
  - `create_citation_source` ([api.py:344](../../../backend/apps/citation/api.py#L344)): parentless + `link_type=="homepage"` → `normalize_host`, full unique check.
  - `_create_root_and_child` ([api.py:417](../../../backend/apps/citation/api.py#L417)): `validate_unique=False` + bare `save()` to distinguish guard-fail from race.
  - `_ensure_root_domains` ([seeding.py:197](../../../backend/apps/citation/seeding.py#L197)): verbatim, exact-host dedup, warn-and-skip on conflict.
    Plan **removes** the first (P1.3 sheds web from `create_citation_source`) and routes derive through the funnel (P2.3), leaving 2 homes (funnel-derive, seeding-declare). Resolves the divergence **only after both phases land**.
- **D8 🟠 ✅ — `normalize_host` is non-idempotent.** Single `www.` strip ([hosts.py:44](../../../backend/apps/citation/hosts.py#L44)): `www.www.foo.com` → `www.foo.com`, which then **shadows** `foo.com`. Plan P1.4 fixes (strip all leading `www.`).
- **D9 🟡 ⏸ — Recognition coupling to `link_type=="homepage"` survives in two spots.** Even after P1.3, the declare path's recognition host derives from `homepage`-typed links only (`_declared_homepage_hosts` [seeding.py:156](../../../backend/apps/citation/seeding.py#L156)). The `domains:` verb (P2.4) decouples it, but P2.4 is explicitly "splittable to its own follow-up" — so the link-type→recognition coupling persists indefinitely if P2.4 slips.

### Dedup / fragmentation

- **D10 🟠 ❌ — Web _children_ fragment on near-duplicate URLs.** Child dedup is exact-string only: `recognize_url` step 2 ([extractors.py:179](../../../backend/apps/citation/extractors.py#L179)) and `get_or_create_web_source` ([extractors.py:342](../../../backend/apps/citation/extractors.py#L342)) match `url=` verbatim. `example.com/x`, `example.com/x?utm=1`, `example.com/x/`, `http` vs `https` → **distinct children under the same root**. The plan solves root-level dedup (D-context #2) but leaves the child-level analog completely unaddressed. This is the same fragmentation disease one level down.
- **D11 🟡 ❌ — Exact child-link match is nondeterministic across roots.** `unique(citation_source, url)` is per-source ([models.py:348](../../../backend/apps/citation/models.py#L348)), so the same URL may be a link on children under two different roots. `recognize_url` step 2 takes `.first()` (default ordering `name`) → recognition silently depends on alphabetical name. `get_or_create_web_source` step likewise `.first()`.

### The god-endpoint & wire-shape drift

- **D12 🟠 ✅ — `create_citation_source` dispatches on input shape.** has-`parent`? has-`url`? has-`identifier`? ([api.py:289–351](../../../backend/apps/citation/api.py#L289)) — one endpoint, four behaviors. P1.3 splits into `pages/` + `records/` + a linkless root create.
- **D13 🟠 ✅ — No `extra="forbid"`; pydantic silently drops stray fields.** `CitationSourceCreateSchema` ([schemas.py:175](../../../backend/apps/citation/schemas.py#L175)) accepts `url`/`link_type`/`link_label`; three client call sites send overlapping subsets. A renamed/removed field becomes a silent no-op, not a 422. P1.3 adds `extra="forbid"`.
- **D14 🟢 ✅ — `link_type` default footgun.** `data.link_type or "homepage"` ([api.py:327](../../../backend/apps/citation/api.py#L327)) stamps `homepage` on child links. Dissolved by P1.3 (no link mint left). Historical rows are Cleanup C3.
- **D15 🟡 ❌ — Scheme-child name rule triplicated.** `f"{root.name} #{id}"` in the client, [api.py:300](../../../backend/apps/citation/api.py#L300) and [extractors.py:279](../../../backend/apps/citation/extractors.py#L279). P1.2 collapses 3→1 in `get_or_create_scheme_child` — _if_ P1.2 lands as written.

### extract / search (user-flagged)

- **D16 🟡 ❌ — Three overlapping input schemas, hand-mapped in the client.** `CitationExtractDraftSchema` (out, [schemas.py:389](../../../backend/apps/citation/schemas.py#L389)), `CitationSourceCreateSchema` (in), `CitationCiteUrlSchema` (in) describe the same web/book source three ways; the client stitches draft→create/cite by hand. P1.3 changes the create shape (drops `url`) → the draft→create mapping must change in lockstep with nothing but `extra="forbid"` to catch a miss. No shared contract.
- **D17 🟡 ❌ — extract draft is cached as a pickled dataclass keyed `extract:v2:*`.** [extraction.py:130](../../../backend/apps/citation/extraction.py#L130), [url_extraction.py:162](../../../backend/apps/citation/url_extraction.py#L162). Any shape change needs a manual `v3` bump or stale drafts deserialize wrong. Versioning is a hand-maintained string.
- **D18 🟡 ❌ — `extract` and `cite_url`/`search` recognize independently → TOCTOU.** Search recognizes a URL ([api.py:237](../../../backend/apps/citation/api.py#L237)); the user describes a site; `cite_url` re-recognizes at finalize ([api.py:466](../../../backend/apps/citation/api.py#L466)). If a more-specific root is seeded between the two calls, the page nests somewhere the user wasn't shown. Inherent to the re-recognize-server-side design; not wrong, but unguarded.
- **D19 🟢 ❌ — Web root is "abstract" by convention only.** Nothing on the backend rejects citing a parentless web/magazine root; `is_abstract` is "a per-request display hint, not an enforced write invariant" ([models.py:259](../../../backend/apps/citation/models.py#L259)). Safe _only_ because every cite path happens to resolve to a child. A future caller that cites a root id directly is unguarded.

### instance / cite (user-flagged)

- **D20 🟡 ⏸ — `_resolve_cite_source_id` inherits D3's `if ref.url` seam** and is the only place web/scheme dedup policy lives for the patch side ([persist.py:236](../../../backend/apps/claim_ingest/apply/persist.py#L236)). It memoizes by `CitationRef`; created sources are deliberately uncounted. Fragility is entirely D3 + D4 surfacing here.
- **D21 🟢 — `CitationInstance` mint** rides only newly-written claims (re-assert-to-add-cite is a documented no-op) and `mint_many` is savepoint-wrapped for slug collisions ([persist.py:317](../../../backend/apps/claim_ingest/apply/persist.py#L317)). This part is sound.

### Test debt (churn the plan creates)

- **D22 🟡 🔶 — `test_api.py` is 115 tests tied to the god-endpoint shape.** P1.3 reworks [test_api.py:544](../../../backend/apps/citation/tests/test_api.py#L544) (parentless-url mint pins removed behavior) and the endpoint split churns many. P2.3 migrates `cite-url` tests off `.example` (the funnel rejects reserved TLDs). Real but bounded.

## 3. Assessment

**What the plan fixes well:** D4, D8, D12, D13, D14 — the active validation/dispatch bites. After Phase 1 the child mint is genuinely converged and validated, and the god-endpoint is gone. These are real and worth doing.

**What the plan leaves standing:**

- **A whole fragmentation class (D10, D11) is invisible to the plan.** It solves root dedup and declares victory on "#2 domain dedup," but the identical disease at the child level — near-duplicate URLs minting duplicate children, nondeterministic `.first()` recognition — is never named. This is the strongest evidence that the plan is treating symptoms at one altitude.
- **The extract surface and attribution are out of scope.** The three overlapping extract schemas, the hand-versioned pickle cache and the recognize-twice TOCTOU (D16–D18) and the unattributed ingest writes (D5/D6) are all untouched.
- **Recognition-host minting (D7) and the link-type coupling (D9) are only fully resolved if _both_ phases land**, and P2.4 is self-described as splittable/deferrable.
- **D3 has since been pulled into Phase 1** (the patch-dispatch seam the user flagged) rather than deferred as the plan had it.

**The direction.** The get-well work is rebuilt around §4 (`CitationSourceTypeStrategy` + the `recognize_url` tidy), not the plan's narrower P1.1 — that resolves D2 and D3/D20 and consolidates D7/D12 (see §4's reach table). Two scope calls are recorded rather than built: **D10/D11 (child-URL fragmentation) is an explicit known limitation** — §4's recognizer is the home if/when it's addressed, but fixing it is not part of this work; and **P2.3 (`cite-url` rounding) may land without P2.4 (`domains:`)** — the plan already marks P2.4 splittable, so D7/D9 stay partially open until it lands. Attribution (D5/D6) and the extract surface (D16–D18) stay out of scope. Phase 2 still rides on a foundation that §4 has straightened first, which is the point.

## 4. The path: one `CitationSourceTypeStrategy`

This is the direction the get-well work takes, replacing the plan's narrower P1.1. The write layer branches on `source_type == "web"` in several shared spots (`skip_locator` [models.py:255](../../../backend/apps/citation/models.py#L255), `ABSTRACT_PARENTLESS_SOURCE_TYPES` [models.py:252](../../../backend/apps/citation/models.py#L252), the implicit web-flatness rule of D2, the recognition-host paths). CLAUDE.md flags exactly this — "branch on type in shared code (`entity_type == "y"`)" — as the smell that should trigger a model-driven pattern. So we give each source type a _strategy_ object, and the next new type (podcast, forum, DOI-keyed work) is a registration, not another `if`.

**One strategy, not two registries.** The behaviors split across two concerns — but only one of them belongs on the type:

| Axis            | web                                         | book                 | magazine   | On the type?                  |
| --------------- | ------------------------------------------- | -------------------- | ---------- | ----------------------------- |
| Hierarchy       | flat (2-level)                              | N-level              | N-level    | ✅                            |
| Parentless root | abstract container                          | concrete (citable)   | abstract   | ✅                            |
| Locator         | child skips (URL is the locator)            | needs                | needs      | ✅                            |
| Child mint      | page-under-root / scheme-child              | edition-under-parent | nested     | ✅ (dispatches to the leaves) |
| Recognition     | scheme **or** host-suffix **or** exact-link | ISBN                 | exact-link | ❌ — see below                |

**Recognition is _not_ on the type, and that's the whole reason it isn't a second registry.** `recognize_url` runs _before_ the type is known — its job is to discover _which_ source a pasted input belongs to. You can't ask the web strategy to `recognize()` because you don't yet know it's web. Recognition is keyed by **input kind** (URL → the scheme/host/exact-link pipeline; ISBN → a lookup), and it is _already_ a registry: `EXTRACTORS` ([extractors.py:59](../../../backend/apps/citation/extractors.py#L59)). So this adds **one** new concept (the type strategy) and **reuses** the recognizer you already own. (Folding recognition onto the type would also relapse into the link→recognition conflation the plan's "Never" section warns against.)

### The strategy — one Python ABC, one impl per type, one registry

A plain Python `ABC` (not a Django model — `CitationSource` stays a single table with a `source_type` discriminator; proxy-model polymorphism is machinery for no gain here), resolved through one registry keyed by the existing `CitationSource.SourceType` enum — _not_ a bare `str`, so a typo or a missing type is a type error, and the small closed set gets an import-time exhaustiveness check:

```python
class CitationSourceTypeStrategy(ABC):
    flat_hierarchy: bool          # web: True  → D2 guard + hierarchy rule
    parentless_abstract: bool     # web/magazine: True → is_abstract
    child_skips_locator: bool     # web: True  → skip_locator
    @abstractmethod
    def create_child(self, parent, ...): ...   # web dispatches page-vs-scheme on the root's identifier_key

STRATEGIES: dict[CitationSource.SourceType, CitationSourceTypeStrategy] = {...}
assert STRATEGIES.keys() == set(CitationSource.SourceType)  # forgetting "podcast" fails at load, not in prod
```

A `TextChoices` member hashes and compares equal to its raw string, so `STRATEGIES[source.source_type]` works directly off a row; coerce with `CitationSource.SourceType(source.source_type)` at the boundary for early failure on a bad value. The strategy is named `CitationSourceTypeStrategy` (not `CitationSourceType`) so it can't be confused with the `CitationSource.SourceType` enum that keys it.

- `skip_locator`, `is_abstract`, and the **D2 web-flatness guard** (`clean()`: "a `flat_hierarchy` type's child must have a root parent") all become strategy reads.
- It carries **behavior, not just flags**: `create_child` differs per type, and an `@abstractmethod` makes the type-checker force every new type to implement it — the exhaustiveness win (no far-off `if` silently forgets the new type). Behavior already factored into named leaves (`create_web_child`, `get_or_create_scheme_child`, per P1.2) stays there; the strategy _dispatches_ to them.

### Tidy `recognize_url` separately (this is what dissolves D3)

`recognize_url` ([extractors.py:119](../../../backend/apps/citation/extractors.py#L119)) is _already_ a hardcoded 3-step pipeline. Tidy it into an ordered list of recognizers over the existing `EXTRACTORS` + host machinery, then route the patch path's `if ref.url` ([persist.py:242](../../../backend/apps/claim_ingest/apply/persist.py#L242)) through the same resolver. The double-spelled web/scheme dispatch (D3/D20) collapses — which is also the plan's own deferred item ("route patch through `recognize_url`"), delivered as a side effect. A new mechanism (DOI, archive.org id) becomes a list entry. This is a refactor of machinery you have, **not** a new parallel registry.

### Prior art — how Wikidata, Wikipedia and Zotero model this

All three corroborate the split (type = thin; recognition/extraction = separate registry), and none uses a class-per-type:

- **Wikidata** — type is a data value (`instance of` P31 → `Q571` book, `Q13442814` scholarly article), an open ontology, no code interface. Books use the **FRBR** model (Work → Expression → Manifestation) — _exactly_ the `book → edition → translation` nesting of D2, so that N-level hierarchy is a recognized model, not ad hoc.
- **Wikipedia CS1** — `{{cite web/book/journal}}` dispatch into one shared Lua engine driven by a declarative `Configuration` module (translation tables + **ID handlers** for ISBN/DOI). The ID-handler table is the direct analog of `EXTRACTORS`; adding a type/identifier is a config-data edit.
- **Zotero** — item types + fields live in a central JSON schema (pure data); you **cannot add custom item types** (closed, curated). The one _programmable_ extension point is **translators** (per-site scrapers) — extraction, a registry keyed by site, never a method on the type.

Takeaways for us: (1) the type itself stays **thin** — keep `CitationSourceTypeStrategy` small; (2) the heavy behavior (extraction/recognition) is universally a **separate input-keyed registry**, validating recognition off the type; (3) type sets are **small and curated** (even Zotero forbids custom types), so don't over-build extensibility.

### Guardrails (so it paves, not over-abstracts)

- **Keep the strategy thin** — properties + the one `create_child` method that genuinely varies. Resist a god-object.
- **Only lift a field onto the strategy once a real `if source_type` exists for it** — every member above has one today; none is speculative.
- **Recognition stays off the type.** Keep `EXTRACTORS` and scheme/host _storage_ separate (the plan's "Never" is right); the type strategy references neither.

### Debt this reaches

The two pieces (the strategy and the bundled `recognize_url` tidy) touch more of the inventory than D2 alone:

Reach (distinct from the Plan legend above): ✅ **fixes** — resolves it · ⚙️ **consolidates** — collapses existing scattered logic into one typed home, residual is reconciliation · 🏠 **localizes** — doesn't address it, but the future fix now has a single home.

| Debt      | Reach           | How                                                                                                                           |
| --------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| D2        | ✅ fixes        | `flat_hierarchy` property + a `clean()` read **is** the web-flatness guard                                                    |
| D3 / D20  | ✅ fixes        | the recognizer tidy collapses the double-spelled `if ref.url` dispatch (the shared resolver both surfaces route through)      |
| D15       | ✅ fixes        | the web strategy's `create_child` owns the `{root} #{id}` scheme-child name rule (via P1.2's leaf)                            |
| D7        | ⚙️ consolidates | recognition-host mint **exists** in three spots with divergent semantics; the web strategy's root-create merges them into one |
| D12       | ⚙️ consolidates | the god-endpoint's `has-url?`/`has-identifier?` if-chain **exists**; per-type dispatch replaces it                            |
| D19       | 🏠 localizes    | the abstract-root rejection doesn't exist (convention only); `parentless_abstract` gives the future guard a data home to read |
| D10 / D11 | 🏠 localizes    | child-URL canonicalization + deterministic match don't exist; the recognizer becomes the single place to add them             |

**Untouched (orthogonal):** D4/D8 (validation/normalization), D5/D6 (attribution), D9 (declare-path link-type coupling — stays off the type by design), D13/D14 (schema hygiene), D16–D18 (the extract surface is input-keyed, not type-dispatched), D21/D22. So this is _not_ a substitute for the rest of Phase 1 — it reshapes the dispatch/structure debt, not the validation, attribution or extract debt.

### Scope & relationship to the plan

- **The `recognize_url` tidy is the spine of a better Phase 1.** It subsumes P1.2's scheme-leaf wiring, the deferred patch-dispatch unification, and D3 — the cleanest home for the "one resolver, two surfaces" symmetry the plan gestures at.
- **The `CitationSourceTypeStrategy` partly _replaces_ P1.1.** "Name the root/child distinction" (`roots()`/`children()`) becomes "declare the types" — and a strategy, unlike a binary, is honest that web is flat while book/magazine nest. It dissolves D2 and the display ifs but isn't load-bearing for the Context bugs, so it's the more optional half.
- This is a foundational reshape, **bigger than the plan as written**: Phase 1 is rebuilt around this rather than the plan's narrower P1.1.
