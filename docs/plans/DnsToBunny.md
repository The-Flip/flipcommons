# Moving nameserver hosting from Joker to Bunny

Joker, the project's DNS provider, was flaky. Sometimes DNS just wouldn't resolve, intermittently.

We moved nameserver hosting to Bunny.net, keeping the domain registered at Joker.

## Outcome: it worked

Delegation changed at 2026-08-18 23:51 UTC. **In the following 12 hours the uptime monitor recorded zero failed checks** — roughly 720 checks at the 60s interval.

| Hypothesis for the current rate         | Expected failures in 720 checks | P(observing zero) |
| --------------------------------------- | ------------------------------: | ----------------: |
| unchanged at the 26.4% pre-cutover rate |                             190 |       2.8 × 10⁻⁸³ |
| back to the 0.9% pre-incident baseline  |                             6.5 |            0.0015 |

The first row disposes of "nothing changed". The second is the more interesting result: **zero failures is significantly better than the pre-incident baseline too.** By the rule of three the current rate is under 0.42% at 95% confidence — at least a 63× improvement, and below where the site sat in July. Whatever produced the low-level 0.9% background rate before 08-12 looks like the same fault running quieter, not a separate one.

The recovery tracks delegation rather than the button press: failures continue for about an hour past the cutover, then stop. That is the 3600s parent delegation TTL draining — resolvers holding `x/y/z.ns.joker.com` kept using Joker, and kept failing, until their entries aged out. An instantaneous cliff would have been the suspicious result, since some resolvers demonstrably still had Joker cached at 23:51.

**What this does not establish.** The cutover changed three things at once — the nameservers, the apex `ALIAS` → `PZ`, and the 60s TTL — so the data cannot say which mattered. It says the fault was somewhere in Joker's path, not which part. And it never explains magnitude: a geo-steering defect should not produce a 26% failure rate. The fix landed without the mechanism ever being identified.

## Open questions

- **Was Joker actually the cause of the flaky DNS?** ~~Never established.~~ Answered after the fact by the [outcome](#outcome-it-worked): removing Joker removed the failures. No test ever positively identified Joker beforehand — the two hypotheses that would have exonerated it were refuted, but that is not the same as implicating it — so the migration proceeded on the independent grounds below. The post-cutover data implicates Joker's path overall without isolating which part of it.
- **Did the migration stand on its own regardless?** Yes: apex geo-steering was measurably broken, `ALIAS` forecloses DNSSEC. [What the cutover settled](#what-the-cutover-settled) records what it fixed.
- **Did the failure reach real users, or only Sentry's checkers?** Never measured. It decided whether this was urgent or housekeeping, and we migrated without knowing.
- **Do we want DNSSEC?** Recommend: now that delegation has settled. Bunny signs zones, but the DS hand-off is manual — enable signing, copy the generated DS, add it at Joker by hand, then confirm the chain validates (`dig +dnssec` showing `ad`, or a DNSViz run). Left out of the cutover deliberately, to avoid coupling two changes and adding a failure mode where a bad DS makes the zone unresolvable for validating resolvers.
- **Do we want CAA?** The zone has none. Cheap to add on Bunny, unrelated to the outage.
- **Does `www` move behind Bunny?** It CNAMEs straight to Railway and exists only to serve Caddy's redirect to the apex. Out of scope; the cutover copied it as-is rather than "fixing" it in passing.

## Scale of the issue

Measured from the Sentry uptime monitor against `https://flipcommons.org/__health`, reading the raw `uptime_results` check stream rather than the downtime issues derived from it.

The monitor ran on a 600s interval with `downtimeThreshold: 1` for the whole measurement window. It was changed to 60s with `downtimeThreshold: 3` on 2026-08-18 20:28 UTC, so figures after that date are not comparable and the baseline below stops at 08-17.

| Period             | Failed checks | Total checks | Failing |
| ------------------ | ------------: | -----------: | ------: |
| 2026-07-21 → 08-11 |            23 |       ~2,448 |    0.9% |
| 2026-08-12 → 08-17 |           228 |         ~864 |   26.4% |

**Roughly one check in four fails.** The rate stepped up sharply on 2026-08-12 — 2.1% on the 11th, 17.4% on the 12th — and has stayed there, ranging 18.8–40.3% daily since. Nothing in this repo changed then: the Bunny apex cutover was 2026-06-05, six weeks earlier, and the monitor ran at the low baseline for three weeks before the step.

Hour-of-day and day-of-week are both flat, ruling out traffic, cron, deploys and business hours.

### Downtime issues are run-starts, not failures

A downtime issue is raised when a run of failing checks begins, not once per failed check. Over the window, 348 failed checks produced 207 downtime issues; in a fully-paged 3-day slice, 182 failed checks formed 105 runs. Any analysis of the spacing between _issues_ is therefore measuring the alerting rule, not the failures. Work from `uptime_results`.

### Failures are independent within each checker region

Sentry rotates the probe round-robin across three regions. Over 2026-08-16 → 08-19 (531 checks, fully paged):

| Region       | Checks | Failed |  Rate | Consecutive-failure pairs (obs / expected if independent) |
| ------------ | -----: | -----: | ----: | --------------------------------------------------------- |
| `us-east-sc` |    176 |     52 | 29.5% | 15 / 15.3                                                 |
| `us-east-va` |    177 |     76 | 42.9% | 34 / 32.4                                                 |
| `us-west-or` |    178 |     54 | 30.3% | 18 / 16.3                                                 |
| **Total**    |    531 |    182 | 34.3% |                                                           |

Two things follow. **All three regions fail**, so this is not one broken Sentry checker — though `us-east-va` runs consistently worse. And within each region the observed consecutive-failure count matches the independence prediction almost exactly, so failures are independent per-probe. Run lengths bear this out: 58 runs of 1, 29 of 2, 10 of 3, 4 of 4, 4 of 5.

### Both failure modes scale together

| Reason class       | Events | Before 08-12 | 08-12 onward |
| ------------------ | -----: | -----------: | -----------: |
| `connection_error` |    114 |           13 |          101 |
| `dns_error`        |     93 |           10 |           83 |

The mix is stable across the step change — roughly 55/45 both before and after — so whatever changed on 08-12 scaled both classes together rather than introducing a new one. That is the main argument for a shared upstream cause; it is not proof of one.

- `dns_error - no record found for Query { ... query_type: AAAA ... }`. Sentry's checker uses Hickory, whose `Ipv4AndIpv6` strategy queries both families in parallel and returns `Ok` if either succeeds, `Err` only when **both** fail, surfacing whichever error arrived first. So this proves Sentry obtained no usable address at all. It does not single out AAAA.
- `connection_error - client error (Connect)`. Durations across all 114: median 16ms, max 130ms, against a 5000ms timeout. Whatever fails, fails immediately. `client error (Connect)` is reqwest's generic connect-phase error — Sentry names `Connection refused` when it recognizes an OS-level refusal — so this proves only that DNS produced an address and no connection was established.

Both occur before the CDN is contacted, so neither is confounded by the edge-cache defect fixed in #716.

### Unexplained: the browser asymmetry

Chrome often works where Firefox and Safari fail. Chrome's host cache is TTL-aware and Firefox's `nsHostResolver` caches on the returned TTL, so cache-vs-no-cache does not account for it. Warm HTTP/2 or HTTP/3 connections that skip resolution entirely, differing resolver configuration, or stale-answer serving are likelier. A symptom report, carrying no diagnostic weight until measured.

### Not yet measured

- **Real-user impact.** The 26.4% figure describes Sentry's checker path. Whether the same rate reaches visitors decides whether this is a monitoring nuisance or a week-long user-facing outage.
- ~~**Whether the apex AAAA is reachable from a US host.**~~ Settled by other means — see [What the cutover settled](#what-the-cutover-settled). The address was a Toronto edge on Bunny's own globally-announced AS, so the unreachability hypothesis fails without needing an IPv6 vantage.
- **Whether Joker drops queries at all.** 390 direct queries from one vantage returned 390 correct answers, so no authoritative packet loss is demonstrated. Multi-region probes against `x/y/z.ns.joker.com` recording rcode, answer count and TTL per family would settle it.

## Leading suspect: the apex is a Joker ALIAS with a 60-second TTL

The apex has no CNAME of its own. Joker resolves `flipcommons-html.b-cdn.net` itself and re-serves the result as synthesized `A`/`AAAA` — an **ALIAS** record, flattened in Joker's infrastructure, re-resolved every 60 seconds:

```text
$ dig +norec flipcommons.org A @x.ns.joker.com +noall +answer
flipcommons.org.  36  IN  A  185.111.111.157     ← TTL counting down from 60
...60 seconds later...
flipcommons.org.  36  IN  A  169.150.219.114     ← different Bunny edge
```

### Every resolver on earth gets the same answer

Because Joker resolves the pull-zone name once and re-serves the result, Bunny's anycast steering is applied to _Joker_, not to the visitor. Querying four geographically-spread public resolvers returns a single flattened answer for the apex, while `static.flipcommons.org` — a real CNAME, resolved by each resolver against Bunny's own nameservers — gets Bunny's own choice:

| Name                     | A                 | AAAA                       |
| ------------------------ | ----------------- | -------------------------- |
| `flipcommons.org` (apex) | `185.111.111.157` | `2400:52e0:1e00:2::1329:1` |
| `static.flipcommons.org` | `169.150.221.147` | `2a02:6ea0:e605:1::915:1`  |

Identical across `8.8.8.8`, `1.1.1.1`, `9.9.9.9` and `208.67.222.222`.

**The IPv4 cost is measured.** From this vantage, connecting to the edge Joker hands out averages **76.3ms**; connecting to the edge Bunny picks for the same client averages **9.6ms**. An 8× penalty, ~67ms added to every connection, paid unconditionally today.

**The IPv6 answer is in a different RIR's space.** Joker serves the apex an address in `2400::/12` (APNIC), while Bunny's own answer for `static` is in `2a00::/12` (RIPE). Bunny anycast may well announce both globally, so this is a lead rather than a finding — but it is the most specific available explanation for a connect that fails in 16ms. If US checkers prefer IPv6 and that address is not reachable from North America, the observed `connection_error` class follows directly, and the `dns_error` class is the same defect when the flattener returns nothing at all. **This vantage has no IPv6 and could not test it.**

### What this does and does not explain

The ALIAS path accounts for the geo-steering cost outright, and plausibly for both failure classes moving together. What it does not account for is magnitude: ~26% of checks failing requires the flattener to be wrong about a quarter of the time, and 390 direct queries to Joker's authoritative servers from here returned 390 correct answers. Either the defect is on a path this vantage never traverses, or the ALIAS is an aggravating factor rather than the cause. The IPv6 lead below was the best candidate for the former and did not survive testing.

Joker's ALIAS records are also incompatible with DNSSEC, so the current apex design forecloses signing the zone at all.

### What the cutover settled

**The IPv6-unreachability lead is refuted.** The apex `AAAA` Joker served sat in `2400:52e0:1a06::/48` — APNIC-registered space, which is what made it look like an APAC address. It is not. Bunny's published [geofeed](https://bunnynet-geofeed.b-cdn.net/bunny-geo-feed.csv) places that `/48` in **Toronto**, and RIPEstat shows it originated by Bunny's own AS200325 and visible to 319 of 320 route collectors. A globally-announced North American edge is not plausibly unreachable from US checkers, so this never explained the `connection_error` class. Registry allocation says nothing about where an anycast prefix is announced.

**The flattening defect is confirmed, on a cleaner control than the one proposed above.** Asking a local resolver for `flipcommons-html.b-cdn.net` — the exact name Joker's ALIAS pointed at — returned a San Jose edge, while Joker's flattened apex returned Toronto. Same pull zone, same hostname, two different answers: proof that steering was applied to Joker's vantage rather than the visitor's, with no need to vary TTL or record type as the `static` control would have.

**The steering cost is mostly recovered, but not universally.** Google and Cloudflare resolve the apex to the same San Jose edge that `static` gets, at **8.0ms** against **156ms** for the mis-steered path — consistent with the 76.3ms/9.6ms pair measured pre-cutover from a different vantage.

It does not hold for every resolver. A resolver that does not send [EDNS Client Subnet](https://www.rfc-editor.org/rfc/rfc7871) still gets a far edge for the apex — while getting the near edge, through that same resolver, for `static`, `media` and for `flipcommons-html.b-cdn.net` itself. Same pull zone, same resolver, 20× difference depending on whether it is reached through the `PZ` record or by hostname. So Bunny's `PZ` flattening steers worse than its own CNAME path does, and the apex geo-steering defect is reduced rather than eliminated. Sampling the apex repeatedly shows it intermittently on ECS-sending resolvers too — Cloudflare consistently near, Google near in 4 of 5 queries.

This is worth a Bunny support report: it reproduces cleanly and does not depend on anything specific to this zone.

**Magnitude remains unexplained.** Nothing above accounts for ~26% of checks failing; the geo-steering defect is a latency and correctness problem, not obviously an availability one. The failure rate did fall — to zero, see [Outcome](#outcome-it-worked) — so the `ALIAS` path was not merely an aggravating factor. But no mechanism was ever found that turns mis-steering into a quarter of connections failing, so this is a fix without an explanation.

Two incidental findings, both corrected in [Hosting.md](../Hosting.md#dns):

- **The parent delegation TTL is 3600, not 86400.** This document originally assumed a 1-day registry TTL and put the rollback window at 48 hours. It is about an hour.
- **Bunny's `PZ` record ignores the TTL field** and serves its own short value. Harmless — the flattened address is anycast, so failover happens in BGP rather than DNS.

## Why Bunny.net

- They have a good reputation both as a company and for nameserving reliability.
- We already use their CDN, so nameserving in the same place means fewer config hops and no new account to manage.
- They are multi-admin, so we don't have to share passwords.
- They are free at our scale.
