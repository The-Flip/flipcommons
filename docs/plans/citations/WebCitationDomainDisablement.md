# Plan: disable web citation subdomain matching and ship

Ship the current `feat/web-citation-fixes` branch **now** — the web-citation create feature (`cite-url` describe-site → page flow) plus the recognition plumbing — with subdomain (longest-suffix) matching **disabled**, so it deploys at zero recognition-behavior change and with no public-suffix footgun. The write-layer cleanup ([CitationsCleanup.md](CitationsCleanup.md)) then starts fresh off `main`; subdomain matching returns later, with its guard, in [CitationDomainGovernance.md](CitationDomainGovernance.md).

## Why ship now, disabled

- **Merge = deploy, and the branch is a coherent unit.** The citation web-create feature, the `CitationSourceRootDomain` recognition plumbing, one supporting `TextField` enhancement, docs. The only thing that makes it unsafe to ship is subdomain matching.
- **Subdomain matching is the one footgun.** Recognition matches by longest label-boundary suffix once enabled, which makes a bare public suffix registered as a recognition host catastrophic (`gov.uk` would match every unrelated `*.gov.uk`), and nothing rejects one today (`https://www.gov.uk/…` → `www.`-strip → `gov.uk`). Closing that needs the PSL guard — deferred to DomainGovernance. **Exact matching can't over-match, so it needs no guard.**
- **Exact matching is byte-for-byte prod behavior.** Recognition on `main` is exact-host (modulo `www.`); shipping it changes nothing observable in recognition. The only new behavior is the additive `cite-url` flow.
- **It resets the branch.** The cleanup then runs on a clean `main`, with no large-branch overhang and no deploy pressure.

## Steps

### DISABLE1: `recognize_url` matches exact host only — `extractors.py`, tests

Flip the recognizer's host step from longest-suffix to exact; leave the suffix machinery built but dormant.

- `recognize_url` step 3 ([extractors.py:212](backend/apps/citation/extractors.py#L212)): match `host=normalize_host(host)` exactly against `CitationSourceRootDomain.host`, **not** `host__in=label_suffixes(host)` + `longest_suffix_match`. The `label_suffixes`/`longest_suffix_match` helpers stay in `hosts.py`, tested but unused — DomainGovernance re-points step 3 at them. **No runtime flag, no second live path** — the exact-only path is the _only_ live path, so the unguarded suffix path is unreachable, not gated. Drop the now-unused `label_suffixes`/`longest_suffix_match` imports from `extractors.py` (else ruff F401 fails `make quality`); G3 re-adds them. The helpers + their `test_hosts.py` coverage are what keep the machinery from bit-rotting.
- **Marker convention (discoverability, not a flag):** at step 3 and on each inverted test, drop a `# SUBDOMAIN-MATCHING-DISABLED (re-enabled in DomainGovernance G3)` comment. DomainGovernance G3 greps that exact marker to find the full set of sites to flip back. It also marks the temporary window in code, pairing with the deliberately forward-looking durable docs below.
- Byte-for-byte prod recognition behavior: exact host (modulo `www.`).
- **TDD (behavior change, suffix → exact) — classify each suffix-test by what it seeds vs cites, then invert only the suffix-only ones.** A test whose cited host is itself a _directly-seeded_ root still resolves under exact matching (exact match, no competition) and must stay green — inverting it would assert a falsehood and fail against the new code. A test whose cited host is only a _subdomain of_ a seeded root no longer resolves — invert it.
  - **Invert (suffix-only — cited host not seeded, only an ancestor is):**
    - extractor — `TestRootDomainRecognition` ([test_extractors.py:108](backend/apps/citation/tests/test_extractors.py#L108)): `test_subdomain_collapses_to_registrable_root` (seeds `american-pinball.com`, cites `s4.…`), `test_subdomain_falls_back_to_parent_when_no_specific_root` (seeds `kineticist.com`, cites `twip.…`), `test_deeper_subdomain_resolves_to_nearest_root` (seeds `american-pinball.com`, cites `cdn.assets.…`).
    - cite-url nesting — `TestCiteUrl.test_subdomain_of_seeded_root_nests_under_it` ([test_api.py:815](backend/apps/citation/tests/test_api.py#L815)) (seeds `american-pinball.com`, cites `s4.…`).

    Each flips to assert the _deferred_ behavior — the subdomain is **not** recognized (raises `DoesNotExist` on the patch path, offers "create new" interactively). Confirm each fails against current suffix matching, then make the flip.

  - **Leave green (cited host is directly seeded → exact match survives):** `TestRootDomainRecognition.test_most_specific_root_wins` and `TestSearchRecognition.test_subdomain_resolves_to_most_specific_root` ([test_api.py:257](backend/apps/citation/tests/test_api.py#L257)) both seed `twip.kineticist.com` _and_ `kineticist.com`, then cite `twip.kineticist.com` — an exact match to the seeded TWiP host, so they resolve to TWiP under exact matching too. The "most specific wins" framing goes moot (no suffix competition) but the assertion holds. Do **not** invert them; optionally drop the now-irrelevant `kineticist.com` co-seed.

- **Durable docs stay forward-looking — do _not_ revise them.** [docs/Citations.md](docs/Citations.md), [docs/DataPatches.md](docs/DataPatches.md) and the `recognize_url` / `CitationSourceRootDomain` docstrings keep describing subdomain matching — the post-DomainGovernance end state, and the shape the code is still built for. They are deliberately _not_ reverted to exact-only for this temporary window: patch ingestion is paused (prod at 0038), so no author hits the gap meanwhile. (Recorded here to pre-empt the recurring "durable docs advertise subdomain matching" review flag — it's a known, accepted gap, not an oversight.)

### DISABLE2: keep patch 0073 resolvable under exact matching — flippatch

The dev rebuild applies every flippatch patch; **0073** (`0073-gameplay-features-on-models.yaml`) cites `s4.american-pinball.com/…` (an asset subdomain of the seeded `american-pinball.com` root), the one genuinely suffix-dependent cite, so it raises `DoesNotExist` under exact matching. Prod is at patch 0038 and 0039+ are rewritable. Two options, simplest first:

- **Defer the cite (zero effort, recommended).** Drop the `cite:` from 0073's gameplay-feature entries — the claims still apply, just without that citation, and there's nothing to unwind later. Re-add the cite once DomainGovernance restores subdomain matching.
- **Declare the asset host (preserves the citation).** Add `s4.american-pinball.com` as a recognition host on the American Pinball root via a `sources:` block — a `homepage`-typed link, minted by the **seeding** path at patch-apply (`ensure_root_source` → `_declared_homepage_hosts` → `_ensure_root_domains` [seeding.py](backend/apps/citation/seeding.py)), **not** the one-shot 0005 migration backfill, which has already run. It must land **in 0073 or an earlier patch** — a higher-numbered patch applies _after_ 0073 and won't help. Trade-off: the extra recognition row wants simplifying back once DomainGovernance's suffix matching makes it redundant.
- Goal: the dev rebuild (DISABLE3) applies cleanly end to end.

### DISABLE3: verify and ship — `feat/web-citation-fixes` → `main`

- **Green gate:** `cd backend && uv run pytest apps/citation apps/claim_ingest -q` — `apps/claim_ingest` is mandatory, not optional: DISABLE1 changes `recognize_url`, and the patch path depends on it (`_resolve_cite_source_id` → `get_or_create_web_source` → `recognize_url`), the exact surface 0073 exercises. Then `make mypy && make quality`.
- **Dev rebuild** (its premise is the named snapshot): reset the dev DB to **`backend/db.pre-0009.sqlite3`** — it carries the ~60 recognition roots (including `american-pinball.com`) that the snapshot + the 0005 backfill establish; a from-empty reset has none of them, so 0073 would "fail" for the wrong reason and many web cites would break. Then `migrate`, `make ingest-patches`; confirm 0073 applies cleanly (per DISABLE2) and the TWiP root recognizes `twip.kineticist.com`.
- **Prod-deploy gate — the 0005 backfill collision audit (confirmed clear).** `0005_backfill_citation_root_domains` ([migration:11](backend/apps/citation/migrations/0005_backfill_citation_root_domains.py#L11)) **fails loud** (never mis-assigns) if two roots share a homepage host. The one known collision — base-seed `This Week in Pinball (TWiP)` vs patch 0031's `This Week in Pinball`, both on `twip.kineticist.com` — is **resolved in prod**: the `(TWiP)` duplicate is deleted (confirmed). A scan of base-seed roots ∪ patch `sources:` ≤0038 finds **no other** host owned by two names, so the predictable collision set is clean. Note the environment divergence: localhost shows a _single_ merged TWiP root because the dev rebuild runs `migrate` before `ingest-patches` (so the recognition row dedups patch 0031 onto the seed root), whereas prod applied 0031 with no recognition table and got two roots — so the dev rebuild cannot reproduce or validate this gate. Residual: roots created _interactively_ in prod aren't in the scan, but `0005`'s fail-loud aborts the deploy safely if one surfaces. No expected pre-work remains.
- Commit the plan docs. Merge `feat/web-citation-fixes` → `main` = **deploy**. Prod stays at patch 0038; recognition behavior unchanged (exact); the `cite-url` flow goes live.

## What ships, what defers

- **Ships now:** the `cite-url` describe-site → page flow, the `CitationSourceRootDomain` table + backfill, the host primitives, exact-host recognition, the `TextField` enhancement.
- **Built but dormant:** `label_suffixes` / `longest_suffix_match` (re-enabled by DomainGovernance G3).
- **Defers:** the write-layer cleanup ([CitationsCleanup.md](CitationsCleanup.md), fresh branch off `main`); subdomain matching + the PSL guard + rounding + `domains:` ([CitationDomainGovernance.md](CitationDomainGovernance.md)); the `CitationInstance` work — access_url, the attachment reshape, the quote field (see [CitationSystemAudit.md](CitationSystemAudit.md)).

## Resulting sequence

1. **Now** — this plan: ship the branch, exact matching. → deploy.
2. **Fresh branch off `main`** — [CitationsCleanup.md](CitationsCleanup.md): the write-layer get-well (C1–C6), behavior-preserving. → deploy.
3. **Later** — [CitationDomainGovernance.md](CitationDomainGovernance.md): re-enable subdomain matching with the public-suffix guard, then rounding + `domains:`. → deploy.
4. **Later** — the `CitationInstance` migration cluster (access_url, then the attachment reshape + quote).
