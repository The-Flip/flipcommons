# Plan: citation domain governance

Enable **subdomain (longest-suffix) recognition matching** safely, then layer the anti-fragmentation features on top: PSL rounding of fuzzy cite URLs and a `domains:` verb for multi-host roots. It builds on the cleaned write layer ([CitationsCleanup.md](CitationsCleanup.md)) and turns on the subdomain matching that [WebCitationDomainDisablement.md](WebCitationDomainDisablement.md) shipped dormant.

This supersedes Phase 2 of [WebCitationDomains2.md](WebCitationDomains2.md) (P2.1–P2.4), re-homed and reordered around one fact that changed after it was written: **subdomain matching is no longer live.** [WebCitationDomainDisablement.md](WebCitationDomainDisablement.md) shipped _exact_ host matching (current prod behavior) with the suffix machinery built but unused, precisely because enabling it without a guard is a footgun. So this plan's first job is to install that guard and flip matching on — together.

## Why the guard and the flip are inseparable

Recognition matches by longest label-boundary suffix once enabled. That makes a bare **public suffix** registered as a recognition host catastrophic: `gov.uk` as a host would suffix-match `dvla.gov.uk`, `hmrc.gov.uk` and every other unrelated `*.gov.uk` site. And a public-suffix host is reachable by ordinary action — `https://www.gov.uk/…` normalizes (`www.`-strip) to `gov.uk`. Exact matching (shipped via WebCitationDomainDisablement.md) can't over-match, so it needs no guard; longest-suffix matching does. The guard (`not is_public_suffix` in `clean()`) and the flip to suffix matching therefore **ship in the same branch** and must deploy together — `G2` before `G3`, never `G3` alone.

## Open questions

- **One commit or two for guard + flip?** Recommendation: two adjacent commits — `G2` (guard, harmless on its own) then `G3` (flip, now safe) — but they merge (= deploy) as one unit. Splitting eases review; it does not license shipping the flip without the guard.
- **Does `G5` (`domains:`) land here or split to its own follow-up?** WebCitationDomains2 marked it splittable — it goes beyond the original Context problems into multi-host roots. Recommendation: land `G1`–`G4` first (that closes the subdomain-match story end to end); `G5` can slip without blocking them.
- **Interim state of patch 0073.** WebCitationDomainDisablement DISABLE2 rewrites 0073 (`s4.american-pinball.com`) to resolve under exact matching, by declaring the asset host on the American Pinball root. Once `G3` enables suffix matching, the natural subdomain cite resolves again — so that interim declaration can be simplified back.

## What earlier branches leave ready

This plan rides on the foundation the disablement and cleanup straightened, so each piece has one home rather than three:

- **`recognize_url` is an ordered recognizer list** (cleanup C6). Suffix matching becomes one list entry's behavior change, not surgery on a hardcoded pipeline.
- **`label_suffixes` / `longest_suffix_match`** are in `hosts.py`, tested, dormant (shipped via WebCitationDomainDisablement.md). `G3` re-points step 3 at them.
- **`CitationSourceRootDomain.clean()`** is the one validated chokepoint every write path runs through. `G2` adds the universal predicate there once.
- **`create_web_child`** is the one validated child-mint leaf (cleanup C4). `G4`'s cite-url rounding mints through it.

## Two distinctions, kept separate

(From WebCitationDomains2 — still the spine.) Keeping these apart is what keeps the plan small.

1. **Where a recognition host comes from — derive vs declare.** _Derive:_ a contributor pastes a fuzzy page URL; the system rounds it to the registrable domain — exactly one place, `cite-url`'s no-match branch (`G4`). _Declare:_ a curator states the host verbatim — patch `homepage:`/`domains:`, Django admin (`G5`). Stored as-is.

- The **universal predicate** (`G2`: normalized ∧ `is_dns_host` ∧ `not is_public_suffix` ∧ root-only) gates _both_. Derivation adds, on top, the `is_reserved_tld` reject + rounding (`G4`) — so a curator may declare a subdomain (`twip.kineticist.com`) verbatim, while a contributor's pasted URL gets rounded and reserved-TLDs rejected.

2. **How a URL resolves — one read (`recognize_url`), two orchestrations (interactive `cite-url`, patch `get_or_create_web_source`), a shared leaf.** They differ only in edge policy (no-match handling, attribution). `G3` enabling suffix matching fixes recognition for **both** surfaces at once, because the read path is shared.

## The commit sequence

Dependency-ordered. 🛑 STOP after each for review before committing. Commit messages: no ephemera.

### G1 — PSL + host predicates — `pyproject.toml`, `hosts.py`

WebCitationDomains2 P2.1. Pure additions to `hosts.py`; no caller yet.

- Add `publicsuffixlist` — `uv add publicsuffixlist==<pinned>`, commit `uv.lock` (CI runs `uv sync --frozen`). Per-module `[[tool.mypy.overrides]]`, not a global flag. Renovate/dependabot entry — a snapshot rots.
- `is_public_suffix(host: Host) -> bool` and `registrable_domain(host: Host) -> Host | None` — `Host` in/out. Build `PublicSuffixList` **once at module load** (the single `Any` boundary). **Honor the PRIVATE section** (`github.io` stays a public suffix → `foo.github.io` is one whole site). `accept_unknown=True` — fail open on a gTLD newer than the bundled snapshot.
- `is_dns_host(host: Host) -> bool` — syntactic only: reject IP literals (`ipaddress`, bracket-stripped `::1`); dot-separated labels (1–63 chars, ≥1 dot, no leading/trailing hyphen, TLD not all-numeric). Pin the charset ASCII `[a-z0-9-]`, **not** `str.isalnum()` (unicode-true). ASCII-only accepts punycode, rejects raw-unicode IDN (a known limitation).
- `is_reserved_tld(host: Host) -> bool` — rightmost label in a frozen RFC-6761/6762 set (`localhost`, `invalid`, `test`, `example`, `local`). A standards constant, not a denylist.
- **Tests (no DB):** each helper; the two-directional `github.io` canary (`foo.github.io` whole, `github.io` a suffix); the `registrable_domain(h) is None ⟺ is_public_suffix(h)` equivalence (the funnel and `clean()` both lean on it — pin it against a snapshot bump).

🛑 STOP.

### G2 — the universal `clean()` guard (the safety prerequisite) — `models.py`

The safety half of WebCitationDomains2 P2.2. Lands **before** `G3` and never ships without it.

- `CitationSourceRootDomain.clean()` ([models.py:403](backend/apps/citation/models.py#L403)): after `normalize_host`, enforce `is_dns_host` **and** `not is_public_suffix`, on every write path (cite-url, admin inline, patch declare). Root-only stays. **Not** `is_reserved_tld` (funnel-only, `G4`), **not** rounding.
- A curator may still declare a subdomain (`twip.kineticist.com`) or a reserved-TLD host verbatim; nobody may store a bare public suffix.
- **Flagged change** — `clean()` can now reject a host it previously accepted. No CHECK constraint, no audit migration (right-size). The dev rebuild covers patch-seeded rows; a prod spot-check (below) covers the rest.
- **Tests:** `clean()` rejects `gov.uk`/`co.uk` (public suffix) and an IP literal, accepts `twip.kineticist.com` (subdomain) and `american-pinball.com` (registrable); the `github.io` canary at the model boundary.

🛑 STOP.

### G3 — enable subdomain matching — `extractors.py`, tests

Reverse WebCitationDomainDisablement's DISABLE1: re-point `recognize_url` step 3 at the dormant suffix helpers. Safe now because `G2` rejects public-suffix recognition hosts.

- `recognize_url` step 3 ([extractors.py:212](backend/apps/citation/extractors.py#L212)): match `host__in=label_suffixes(host)` + `longest_suffix_match` against `CitationSourceRootDomain.host`, most-specific-first — replacing the exact `host=` lookup DISABLE1 installed. Re-add the `label_suffixes`/`longest_suffix_match` imports DISABLE1 dropped. This is the single behavior flip; `get_or_create_web_source` and `cite-url` inherit it through the shared read path.
- **Find the full set of sites to flip:** `grep -rn 'SUBDOMAIN-MATCHING-DISABLED' backend/apps/citation/` — DISABLE1 left that marker at step 3 and on each inverted test. Re-point step 3, re-invert those tests to assert suffix resolution and remove the markers.
- **Tests:** restore the subdomain-cite coverage DISABLE1 inverted — `s4.american-pinball.com/…` resolves to the seeded `american-pinball.com` root; an asset host wins over its parent for its own subtree; a public-suffix host can't be a root to over-match against (ties `G2` and `G3` together in one test).
- **Patch:** with suffix matching live, 0073's `s4.american-pinball.com` cite resolves again (see Open Questions for its interim state).

🛑 STOP.

### G4 — the funnel + cite-url rounding — `hosts.py`, `api.py`

The funnel half of WebCitationDomains2 P2.2 + P2.3. Anti-fragmentation: a contributor pasting a fuzzy subdomain URL with **no** existing root mints a root at the _registrable domain_, not the bare subdomain, so future cites under the same site collapse to one root.

- `root_host_from_url(url) -> Host` in `hosts.py`, HTTP-free: `urlparse(url).hostname` → `normalize_host` → `is_dns_host` → `is_reserved_tld` reject → `registrable_domain` (`None` = bare public suffix → reject) → return the rounded `Host`. Each gate raises a typed `HostError(reason)` — never `HttpError`. Kept pure for unit-testability and one documented validate-before-round order.
- `cite-url`'s no-match branch ([api.py:445](backend/apps/citation/api.py#L445)): `try: host = root_host_from_url(url) except HostError → HttpError(422, …)`, at the **top**, before any write; synthesize `https://{host}/`; mint the `CitationSourceRootDomain` at `host`; `create_web_child` under it (the cleanup C4 leaf). The funnel's only caller — the patch path _raises_ on no match, it never derives.
- **Migrate the `cite-url` rooting tests off `.example`** (the funnel `HostError`s reserved TLDs) → real registrable domains. Declare-path / `recognize_url` `.example` fixtures don't hit the funnel and stay.
- **Tests:** no-match rounds `s4.american-pinball.com/…` → an `american-pinball.com` root (assert `CitationSourceRootDomain.host` **and** synthesized `homepage.url == "https://american-pinball.com/"`); 422 on IP / reserved-TLD / bare-suffix before any write.

🛑 STOP.

### G5 — declare: the `domains:` verb (splittable — see Open Questions) — `seeding.py`

WebCitationDomains2 P2.4. A diff, not a rebuild: `_roots_owning_hosts`, `_ensure_root_domains`, `ensure_root_source` already do verbatim-host minting and exact-host dedup.

- **Parse `domains: [h, …]`** off the patch node; add it to `SeedSource`; validate (list of host strings).
- **Union with the declared homepage host** into `_ensure_root_domains(source, hosts, …)` — `hosts = _declared_homepage_hosts(links) ∪ normalize_host(each domains entry)`. One row per distinct host; existing dedup + warn-skip reused unchanged.
- No rounding (declare). `homepage:` stays display-only-plus-its-host; `domains:` adds hosts for multi-host roots (rebrand, `.com`+`.co.uk`, asset host) — replacing the v1 "second homepage link" hack.
- **Tests:** `domains:` adds verbatim hosts (incl. a subdomain — no round); `homepage:` + `domains:` union; re-declare a root by name with a new `domains:` host → adds a row, no duplicate; dedup by exact host; hosts spanning two roots → warn + skip, no `IntegrityError`.

🛑 STOP.

## Decisions

- **Recognition is longest-suffix and PSL-free.** Rounding (PSL) is a write-time concern, in the funnel only (`G4`). The read path (`G3`) never consults the PSL — it suffix-matches stored hosts, every one of which is canonical-from-`cite-url` or verbatim-from-a-curator, so dedup stays exact-host.
- **Own the recognition host as a fact** (`CitationSourceRootDomain`), decoupled from the display `homepage` link. Set at creation; thereafter independent of display-link edits. A root's recognition hosts are the `homepage:` host (if any) ∪ the `domains:` list (declare), or the rounded host (`cite-url` derive). Never read back out of a link.
- **`accept_unknown=True`** for `registrable_domain` — fail open on a TLD newer than the bundled PSL snapshot. `is_reserved_tld` still rejects RFC special-use names, so the only accepted-junk case is a genuinely-unknown **real** gTLD — intended.
- **Right-size to the threat model.** Volunteer-run museum catalog, Activity-gated contributors, admin gardening — not a hostile public API. `clean()` is the gate for every real writer; no CHECK constraints, re-normalizing migration or audit migration.

## Out of scope / known limitations

- **Asset hosts on a different registrable domain** (a third-party CDN outside the publisher's domain) won't suffix-match — longest-suffix only collapses within one registrable domain. Fix: a `domains:` row (`G5`) or an admin-inline domain.
- **Non-PSL "subdomain-per-publisher" platforms** collapse to one shared registrable-domain root under `cite-url` rounding until a curator splits them with `domains:` rows.
- **A genuinely-unknown real gTLD** rounds via `accept_unknown=True` rather than 422-ing — accepted fail-open; the renovate bump keeps the snapshot current.
- **Raw-unicode IDN hosts are rejected** (`is_dns_host` is ASCII-only) — an internationalized recognition host must be punycode (`xn--…`). Revisit (`idna` in `normalize_host`) only if a real publisher needs it.
- **Admin "promote a subdomain into its own root" gardening tool** — creates a more-specific root and reparents the children that route to it. Orthogonal to _declaring_ a host; this is _reparenting_ at gardening time. Until then, creating a more-specific root leaves existing children under the ancestor (a temporary split).

## Never

- **Auto-reparent on save** — regrouping is deliberate gardening.
- **Fold TWiP into Kineticist** — TWiP stays its own publication (`domains: [twip.kineticist.com]` or its `homepage:` host).
- **Unify scheme- and host-recognition _storage_** — a scheme root recognizes via `identifier_key` (one value, regex match); a web root via `CitationSourceRootDomain` host (many values, suffix match). Different cardinality, different match algorithm. `recognize_url` already unifies them at the _read_ point — the only place unification pays. Merging the storage is the "looks similar, isn't" over-abstraction that bred the original link→recognition mess.

## Verification

```bash
cd backend && uv run pytest apps/citation apps/claim_ingest -q
uv run python manage.py shell -c "from apps.citation.extractors import recognize_url; print(recognize_url('http://s4.american-pinball.com/games/gtf/docs/manual.pdf'))"
# → Recognition(parent_name='American Pinball', ...)   (subdomain now resolves)
make mypy && make quality
uv sync --frozen            # G1 adds publicsuffixlist; the lockfile must satisfy a frozen sync
```

- **Before enabling the flip on prod** (`G3`): spot-check that every existing `CitationSourceRootDomain.host` value is non-public-suffix and DNS-valid (a one-line query). Existing rows predate the `G2` guard, and turning on suffix matching is what makes a stray public-suffix row dangerous — this is the gate.
- **Dev rebuild:** reset the dev DB, `migrate`, re-apply patches — re-runs every host through the `G2` guard and every subdomain cite through `G3`'s matching. Confirm 0073 (or its interim form) resolves under suffix matching.
