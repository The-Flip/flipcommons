# Client IP Trust

Make the client IP we use for rate-limiting trustworthy, then bump Caddy and wire dependency-update automation while we're in the area.

## Why

`_client_ip` in [apps/core/rate_limits.py](../../backend/apps/core/rate_limits.py) reads the left-most non-empty entry of `X-Forwarded-For`. On Railway, the XFF that arrives at Django holds **Railway's rotating internal proxy IP** (`100.64.0.X`, last octet rotates per request — see [Railway probe results](#railway)), not the real client IP. Consequence: each request from the same client lands in a different rate-limit bucket. The IP-keyed limiters are **non-functional today** — not bypassable by an attacker so much as silently bypassed by Railway's proxy fabric for everyone.

Severity per endpoint (Session 2 onboarding flow):

- `signup_check_ip` / `signup_submit_ip` — IP throttle non-functional, but a session-keyed limiter still applies as a real backstop. Per-session throttle survives.
- `signup_cancel_ip` — IP is the only limiter; no session bucket. **No effective rate limiting on this endpoint.**

Secondary motivations bundled into the same change:

- **Robustness across infrastructure changes.** The current behavior is an accident of Railway's edge architecture (Railway strips client-supplied XFF, populates `X-Real-IP` with the real client IP, then writes its own rotating internal IP into XFF). If we ever move off Railway, change Railway's edge config, or add a CDN, the same code could silently start trusting attacker-supplied XFF instead. Making the trust source explicit and gated by an env var means the trust assumption survives migrations.
- **Caddy 2.11.2 is one patch release behind.** 2.11.3 fixes a FastCGI RCE, two admin-API auth bypasses, and a more thorough vars-module CVE patch. Bumping manually here preempts the next Dependabot run by a few days for the security content; it doesn't fix a missing signal — Dependabot already covers the Dockerfile, and in fact closed an unrelated year-long drift (2.10.2 → 2.11.2, [#204](https://github.com/The-Flip/flipcommons/pull/204)) three weeks before this plan was written.

## Decisions

### Django reads `X-Real-IP`, not `X-Forwarded-For`

`_client_ip` reads `HTTP_X_REAL_IP` (with `REMOTE_ADDR` fallback), gated by a `RATE_LIMIT_TRUST_PROXY_HEADERS` setting. Django never parses XFF. Railway already sets `X-Real-IP` correctly at its edge (cross-checked against the edge log's `srcIp` field — see [Railway](#railway)), so Caddy doesn't need to compute or rewrite it; Caddy's job is just to forward what Railway sent.

**Primary reason: failure-mode asymmetry across infrastructure changes.** The current safe behavior depends on Railway's edge. If a future migration (different host, removed Railway, added CDN) changes upstream XFF semantics, the choice of header we read determines what happens:

- **X-Real-IP fails closed.** If the trusted upstream stops setting it, the header is absent. `_client_ip` falls back to `REMOTE_ADDR=127.0.0.1`. Every request shares one bucket. Annoying, observable (legit users see 429s within minutes), fixable. **Not a security bug.**
- **X-Forwarded-For fails open.** Same migration, but XFF is the conventional header that _every_ upstream populates — possibly with attacker-supplied content, possibly with chain semantics that our left-most parser misinterprets. The recurrence is silent: no symptom until someone tries the bypass.

This asymmetry is permanent — a property of the header shapes, not of any specific upstream.

**Secondary reasons:**

- **Deletes the parsing-bug class entirely.** `_client_ip` becomes one line: read a scalar, fall back to `REMOTE_ADDR`. No `.split(",")`, no left-vs-right-most decision, no trusted-proxy bookkeeping. A future code review never needs to reason about list semantics.
- **Defense in depth.** The `RATE_LIMIT_TRUST_PROXY_HEADERS=False` default ([Step 2](#step-2-_client_ip-hardening)) is the _second_ fail-closed layer behind this same failure mode — if the env var is unset or rolled back, proxy headers are ignored entirely and bucketing keys off `REMOTE_ADDR`. Two independent layers both fail safely on the same class of drift.
- **Convention argument for XFF is weak here.** The chain past Caddy is single-hop to Django on loopback. The only readers of the client IP are [apps/core/rate_limits.py](../../backend/apps/core/rate_limits.py) and [apps/provenance/rate_limits.py](../../backend/apps/provenance/rate_limits.py), both of which want a scalar. We're already (per Out of scope) accepting that the XFF chain is discarded at Caddy regardless of header choice, so "preserve the chain for analytics" isn't a lever that exists.

**Costs accepted:**

- One-time rewrite of any existing rate-limit tests that inject `HTTP_X_FORWARDED_FOR`. Bounded, observable at test-write time.
- Slight unconventionality vs. the broader Django/proxy ecosystem. Mitigated by a docstring on `_client_ip` explaining the choice.

**Implication for Caddy:** the headers reaching Django need sanitization for two distinct reasons — the RFC 7239 `Forwarded:` header is attacker-controlled and must be stripped, and XFF currently holds Railway's rotating internal IP, which is a nuisance for any future XFF reader. See [Step 1](#step-1-caddyfile-change).

## Railway architecture (confirmed)

Confirmed via the Railway dashboard on 2026-05-14:

- **Public Networking uses Railway's HTTP routing**, not TCP Proxy. `flipcommons.org` and `www.flipcommons.org` both forward to container port 8080 (where Caddy listens). Railway terminates TLS; Caddy receives plain HTTP.
- **Proxy chain is: client → Railway edge (Envoy) → Caddy (`:8080`) → Django/Node.** Three hops. Django's `REMOTE_ADDR` will always be `127.0.0.1` because Caddy reverse-proxies to loopback (`reverse_proxy 127.0.0.1:{$DJANGO_PORT:8000}`), regardless of what's upstream of Caddy.
- **CDN caching is disabled** on both custom domains (the per-domain "Enable CDN caching" toggle is off). This plan assumes it stays off. If enabled later:
  - Railway's CDN is Cloudflare-backed (museum has vetoed Cloudflare per existing media-hosting decision, so this is a non-trivial policy question, not just a perf toggle).
  - `trusted_proxies private_ranges` would no longer be sufficient — CDN POPs are public IPs and need explicit ranges or a trust mechanism.
  - 429 responses would need `Cache-Control: no-store` to prevent the CDN from serving cached rate-limit rejections to other callers.
- **`flipcommons-production.up.railway.app` is Railway's auto-assigned "primary service domain"** and must not be deleted — Railway uses it for healthchecks, dashboard links, and possibly preview environments. Its attack surface is identical to `flipcommons.org` (same edge, same proxy, same headers), so keeping it does not add risk.
- **TCP Proxy** is a separate, currently-unused feature for exposing raw TCP. Not relevant here. If added in the future, it would create a second listener that bypasses Railway's HTTP edge — but it would not be used for the rate-limited HTTP endpoints, so it does not affect this plan.

## Verified facts

### Caddy 2.11

- `trusted_proxies private_ranges` works as an inline `reverse_proxy { }` subdirective; `trusted_proxies static private_ranges` works at the global `servers > trusted_proxies` level. Caddy docs strongly recommend the global form.
- Default XFF parsing is **left-to-right** ("the first untrusted IP address found becomes the real client address"). This is **wrong for append-style upstreams** — the left-most position is exactly what an attacker controls. `trusted_proxies_strict` flips to right-to-left and is **required** for append-style proxies (HAProxy, CloudFlare, ALB, Railway-likely).
- `{client_ip}` placeholder resolves to the trusted-resolved client IP (falls back to remote peer when no trusted proxy is in front).
- Caddy's docs are silent on what XFF value it forwards upstream after resolution. Don't rely on undocumented behavior — set it explicitly via `header_up X-Forwarded-For {client_ip}`.

### Railway

Confirmed on 2026-05-14 by deploying `/api/probe` against `https://flipcommons.org/api/probe`. Three sources of evidence: Django response from the probe endpoint (headers as seen by the app), Railway's edge HTTP log (per-request metadata at the public ingress), and Caddy's deploy-log output.

- **Railway's edge strips client-supplied `X-Forwarded-For` entirely.** Attacker headers `X-Forwarded-For: 9.9.9.9` and list-form `9.9.9.9, 8.8.8.8` never survive to Caddy. Verified across scalar, list, and combined-spoof cases. The attacker-controlled XFF bypass premise that originally motivated this plan **does not apply** on Railway as-deployed — that's not a reason to relax the plan (see [Defense in depth](#decisions)), but it changes the threat model description in [Why](#why).
- **`X-Real-IP` is set by Railway's edge to the real client public IP, and is not attacker-spoofable.** Sending `X-Real-IP: 9.9.9.9` directly is overwritten before Caddy sees it. Stable across repeated requests from the same client. Cross-checked against Railway's edge log `srcIp` field, which matches `X-Real-IP` at Django exactly — the end-to-end chain is verified.
- **Railway → Caddy is over IPv6 in the RFC 4193 ULA range (`fd00::/8`).** Railway's edge HTTP log reports `upstreamAddress` as an `fd…` IPv6 address on port 8080 (Caddy's listener). Caddy's actual TCP peer is therefore IPv6, not IPv4.
- **The `100.64.0.X` rotating IPv4 that appears in XFF at Django is not Caddy's TCP peer** — Caddy's peer is the IPv6 ULA above. The `100.64.0.0/10` (RFC 6598 CGNAT) value is something Railway writes into the XFF header itself before forwarding to Caddy, and the last octet rotates per request (observed `100.64.0.2` through `.8` across 8 requests from one client — Railway runs multiple internal proxy nodes). Caddy then forwards this XFF unchanged.
- **Practical consequence: the current XFF-based `_client_ip` is mis-keyed onto Railway's rotating internal IP.** Per-IP rate limiting buckets each request from the same client into a different bucket. This is non-functional for _everyone_, not just attackers — a worse-than-expected status quo, and it makes [Step 3](#step-3-_client_ip-hardening) a functional bug fix, not just a hardening.
- **`trusted_proxies` configuration in Caddy is not needed for this plan.** `X-Real-IP` is trustworthy at Caddy's ingress (Railway's edge guarantees it), and we're not reading XFF. If we ever did want Caddy to resolve `{client_ip}` from XFF, Caddy's `private_ranges` keyword **does** cover IPv6 ULA (`fc00::/7`, which includes `fd00::/8`), so trusting Caddy's actual peer would work out of the box — but again, moot because we don't need it.
- **`Forwarded` (RFC 7239) passes through verbatim and IS attacker-controlled.** Sending `Forwarded: for=9.9.9.9` produced `forwarded="for=9.9.9.9"` at Django. No code reads this header today, so not actively exploitable, but [Step 2](#step-2-caddyfile-change) should sanitize it as defense in depth (a future logging shim, geoip lookup, or middleware that reads `Forwarded:` would inherit the bug).
- **`X-Forwarded-Proto` arrives at Django as `http`, not `https`**, even though Railway terminates TLS at its public edge. Railway → Caddy is plain HTTP/1.1 (per Railway edge log `upstreamProto: HTTP/1.1`). Tangential to this plan but worth a separate follow-up — affects any code that branches on request scheme (Django's `SECURE_PROXY_SSL_HEADER`, redirect-to-https logic, secure-cookie decisions).
- **Django's `REMOTE_ADDR` is `127.0.0.1`**, as predicted by the architecture (Caddy reverse-proxies to loopback).

## Proposal

We ran a probe; findings in [Railway](#railway). The Caddyfile below reflects the results.

### Step 1: Caddyfile change

```caddy
:{$PORT:8080}

@www host www.flipcommons.org
handle @www {
    redir https://flipcommons.org{uri} permanent
}

request_header -Forwarded

@django path /api /api/* /djadmin /djadmin/* /media/* /static /static/*
handle @django {
    reverse_proxy 127.0.0.1:{$DJANGO_PORT:8000} {
        header_up X-Forwarded-For {http.request.header.X-Real-IP}
    }
}

handle {
    reverse_proxy 127.0.0.1:{$NODE_PORT:3000} {
        header_up X-Forwarded-For {http.request.header.X-Real-IP}
    }
}
```

What this does and doesn't do:

- **Strips `Forwarded` at site level** — `request_header` works fine for arbitrary headers; this is the one attacker-controlled channel the probe surfaced.
- **Rewrites `X-Forwarded-For` inside each `reverse_proxy` block via `header_up`** — not at site level, despite the duplication. Caddy's `reverse_proxy` has special handling for `X-Forwarded-*` headers that overrides any site-level `request_header` mutations (per [Caddy docs](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#defaults): _"By default, Caddy passes incoming headers to the backend without modification, with the exception of X-Forwarded-For, X-Forwarded-Proto, and X-Forwarded-Host."_). Empirically verified during deploy: a site-level `request_header -X-Forwarded-For` left Django seeing the original Railway-injected `100.64.0.X` value, while `header_up` inside `reverse_proxy` correctly overwrites it. `header_up` is the proxy-aware path.
- **No conditional gate on X-Real-IP presence.** Earlier drafts gated the rewrite on a `@has_real_ip` matcher so XFF would be stripped (rather than blanked) if X-Real-IP were absent. Dropped because `header_up` doesn't accept matchers, and adding one via `handle` blocks isn't worth the complexity for a hypothetical failure mode Railway never produces in practice. The "X-Real-IP is present at the proxy boundary" assumption joins `RATE_LIMIT_TRUST_PROXY_HEADERS=true` as a deployment contract.
- **`Forwarded` strip stays site-level** because it has no `reverse_proxy` special-casing — `request_header` is the right tool there, and keeping one directive at site level (instead of duplicating across both reverse_proxy blocks) is the lighter touch.
- **Two `header_up` directives are duplicated** across the @django and catch-all Node blocks. A Caddyfile snippet (`(name) { }` + `import name`) was attempted to dedupe, but snippets must be defined at global scope (before any site address) and inline definition mid-site silently breaks the deploy. One-line duplication won; revisit if the directive grows.
- **Does NOT add `trusted_proxies`, `trusted_proxies_strict`, or rewrite `X-Real-IP`.** Railway's edge already populates `X-Real-IP` correctly and cannot be overridden by clients (verified by probe). Computing it ourselves from XFF would be strictly worse. If we later move off Railway, this is the first thing to revisit — `trusted_proxies` becomes relevant when the upstream stops being trustworthy by itself.

**Verify after deploy:** spin the probe endpoint back up briefly (or check via a one-off Django shell + curl) to confirm `Forwarded` is absent at Django and XFF equals the real client IP, not `100.64.0.X`.

### Step 2: `_client_ip` hardening

In [backend/apps/core/rate_limits.py](../../backend/apps/core/rate_limits.py):

- Add `RATE_LIMIT_TRUST_PROXY_HEADERS` Django setting, **default `False`**. The setting gates whether `_client_ip` reads `X-Real-IP` at all.
- When `False`: `_client_ip` returns `REMOTE_ADDR` only. Safe default for dev, tests, and any container where the proxy chain isn't sanitized.
- When `True`: `_client_ip` returns `request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "0.0.0.0"`. One-line function, no list parsing, no proxy-chain interpretation.
- Production env sets the env var to `True`. The trust assumption becomes a deployment contract, not implicit code behavior.

This setting is the **second fail-closed layer** behind the X-Real-IP choice ([Decisions](#decisions)). Both layers protect against the same class of drift: if either the Caddy `header_up` line disappears _or_ the env var rolls back to default, the system degrades to "everyone shares a `127.0.0.1` bucket" — annoying and observable, not a security bug.

A docstring on `_client_ip` should briefly note both: why it doesn't read XFF (parsing-bug class, fail-closed posture) and why the setting defaults to `False` (defense in depth). Future readers shouldn't have to dig into git history to understand a deliberately boring function.

Before writing the implementation: **audit existing tests** for any that inject `HTTP_X_FORWARDED_FOR` or `HTTP_X_REAL_IP` expecting distinct-IP behavior. With the default flipped to `False`, those tests will silently bucket on `127.0.0.1` and pass for the wrong reason. They need to either set `RATE_LIMIT_TRUST_PROXY_HEADERS=True` explicitly _and_ switch from XFF to `X-Real-IP` injection, or be rewritten to use `REMOTE_ADDR`.

Add tests in [test_rate_limits.py](../../backend/apps/core/tests/test_rate_limits.py):

- With `RATE_LIMIT_TRUST_PROXY_HEADERS=False` (default), attacker-supplied `X-Real-IP` and `X-Forwarded-For` are both ignored; bucket keys off `REMOTE_ADDR`. **The critical regression test** — if a future deploy accidentally rolls the setting back to default, no bypass.
- With `RATE_LIMIT_TRUST_PROXY_HEADERS=True`, `X-Real-IP` is read; `X-Forwarded-For` is still ignored (asserts the parsing-bug class is gone).
- Setting toggles per-test via `settings` fixture; no module-level state.

### Step 3: Caddy 2.11.2 → 2.11.3

Update [Dockerfile:29](../../Dockerfile#L29). One-line bump. Security patches (FastCGI RCE, admin API auth bypass) are unrelated to the XFF work but unsafe to defer.

### Step 4: Dependabot for the Dockerfile

**Already done** — discovered during implementation. [.github/dependabot.yml](../../.github/dependabot.yml) has a `docker` ecosystem entry on `/` with a weekly schedule, which covers all base images in the root [Dockerfile](../../Dockerfile) (Caddy, Node, Python). The next 2.11.x → next-version Caddy bump will land as an automated PR.

No change needed in this work.

## Out of scope

- **Refactor of `apps/provenance/rate_limits.py`** to share code with the new core module. Different keying (per-user vs. session/IP), small dedup payoff. Deferred follow-up.
- **Trusted-proxy ranges for the dev environment.** Dev never has a proxy in front, so the safe default (proxy headers off) means tests + local dev key off `REMOTE_ADDR=127.0.0.1`. Acceptable since dev rate limits aren't security boundaries.
- **Preserving the full XFF chain for geo-IP / abuse analytics.** The Caddy `header_up` overwrites/replaces the chain regardless of which header strategy we pick, so the chain is gone past Caddy. If we ever want it back, easier to revisit then than to design around a hypothetical now.
- **Enabling Railway's CDN caching.** Currently off, and stays off in this work — see [Railway architecture](#railway-architecture-confirmed) for what would need to change if it were ever turned on.

## Sequencing

Separate branch (`feat/client-ip-trust`), separate AI session. One commit per logical step is fine, but a single commit covering all four steps is also acceptable since the review boundary is the PR, not the commits.

Lands to `main` **before** the `feat/user-chosen-usernames` branch ships signup publicly. Doesn't block committing onboarding code on that branch — the rate limiters function on the session axis without this change; the IP axis is currently non-functional but neither relied on nor exploitable in a way that's worse than not having it.

After merge, rebase `feat/user-chosen-usernames` onto `main` so the signup tests benefit from the hardened `_client_ip` semantics (the `RATE_LIMIT_TRUST_PROXY_HEADERS` setting defaults to `False`, so existing tests using `REMOTE_ADDR` will continue to pass unchanged).

**Rebase conflict resolution — important.** Both branches touch `backend/apps/core/rate_limits.py`. This branch lands a minimal module containing only the hardened `_client_ip` plus a placeholder docstring. `feat/user-chosen-usernames` independently created the full module (RateLimitExceededError, RateLimitSpec, signup specs) with an **older, unhardened** `_client_ip` that reads `X-Forwarded-For`. Naively taking "theirs" at rebase silently reverts the hardening — and there is no compile error or test failure that would catch it, because the other branch's tests inject XFF and expect distinct-IP behavior.

Resolution: keep this branch's `_client_ip` body (and the trust-gate import of `settings`), keep the other branch's surrounding classes/specs, and drop this branch's placeholder paragraph from the module docstring. Then audit the other branch's tests per [Step 2](#step-2-_client_ip-hardening) — any test that injects `HTTP_X_FORWARDED_FOR` expecting distinct buckets must either set `RATE_LIMIT_TRUST_PROXY_HEADERS=True` and switch to `HTTP_X_REAL_IP`, or be rewritten to use `REMOTE_ADDR`.

## Tests

- `test_rate_limits.py` — both modes of `RATE_LIMIT_TRUST_PROXY_HEADERS`, including the regression case described in [Step 2](#step-2-_client_ip-hardening).
- No backend test asserts Caddyfile contents — the Caddy config is verified by the post-deploy probe re-run ([Step 1](#step-1-caddyfile-change)) and the `_client_ip` setting-gated tests, not by Python.
