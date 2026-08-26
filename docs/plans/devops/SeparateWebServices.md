# Separate the web services

We've been having a problem with the Railway web service crashing; see [Github issue #726](https://github.com/The-Flip/flipcommons/issues/726).

To make Railway more robust, we could split the single Railway web service — Caddy, Django/Gunicorn and SvelteKit Node SSR in one container — into one service per process, so Railway supervises each independently.

My understanding is that this would be a more standard topology than our current system. What we want is a BONE STANDARD Railway topology and deployment, that uses Railway exactly like best practice teams do. I don't know what that looks like. The rest of this doc is AI-generated and I don't vouch for it. If it proposes anythign that's not absolutely Railway-standard and standard best practice, let's not do that. If it suggests anything that could dig us an even deeper and different hole than our current Railway crash behavior, it's a hard pass.

## Open questions

- **What does this actually cost?** Railway bills by resource usage rather than per service, so three containers is not three times the bill — but each carries its own idle memory footprint, and [SmallTeam.md](../../SmallTeam.md) puts the pain threshold at $10/month. Needs measuring against the current single-service usage before committing, not estimating.
- **Who runs migrations?** `preDeployCommand` currently runs [`scripts/predeploy`](../../../scripts/predeploy) (`check --deploy` then `migrate`) once for the one service. Split, only the Django service should run them, and the SSR service must not go live against a schema that hasn't migrated yet. Railway has no cross-service deploy ordering primitive, so this needs a deliberate answer.
- **How much deploy skew can we tolerate?** See [Deploy lockstep](#deploy-lockstep-is-lost).
- **Does Caddy stay?** [Railway has no path-based routing across services on one domain](#caddy-has-to-stay-a-service), so something must own the public origin and fan out. Caddy already does it and the config is written. The alternative is moving that routing into the SSR service, which means SvelteKit proxying `/api/` and `/djadmin/` to Django — plausible, but it puts Django's availability behind Node's, which is most of what this plan is trying to undo.
- **Is [s6-overlay](#s6-overlay-in-one-container) the cheaper answer?** It solves supervision without touching topology, at the cost of owning an init system.

## Why

### One process crash is a full-site outage

[`scripts/start-production`](../../../scripts/start-production) starts all three processes and watches them in a shell loop. When any one exits, it kills the other two and the container exits. That is deliberate — [Hosting.md](../../Hosting.md#process-model) calls it "simple and fails closed" — but it means the blast radius of any single fault is the entire site.

The faults we have seen are not distributed evenly across the three processes. Both known incidents were the Node SSR process dying on the same class of bug:

| Date               | Fault                                                                                                                    | Outcome                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| 2026-08-17         | Uncatchable assertion in Node's bundled undici, raised from a socket event handler while reading a response from Django  | Container exited and **stayed down for hours** |
| 2026-08-25 → 08-26 | Same assertion, triggered by crawler hits on `/sitemap.xml` ([#726](https://github.com/The-Flip/flipcommons/issues/726)) | 7 crash/restart cycles in 17 hours             |

In both, Django was healthy and logged nothing. The API and the admin went down because a _different_ process in the same container died.

### Railway's restart behavior is not something we can count on

The two incidents above are the same fault class with opposite recovery outcomes. The August 17 deployment was already configured `ON_FAILURE` with 10 retries and still stayed down for hours; the August 25 one restarted seven times without intervention. [Hosting.md](../../Hosting.md#process-model) states the operating assumption bluntly: **do not assume Railway restarts the container.**

That uncertainty is itself an argument for the split. Railway restarts a single-process service natively and reliably — it is a first-class platform behavior, not an inference about how the platform reacts to a shell script's exit code. Today we are relying on the latter.

### Supervision is the platform's job

The current entrypoint is not a supervisor and should not become one. Making it restart children individually means handling drain on `SIGTERM`, distinguishing a crash loop from a flaky child, and reaping grandchildren that still hold a listening socket. Those are the problems an init system exists to solve, and a volunteer project has no business solving them in a `while` loop. [SmallTeam.md](../../SmallTeam.md) is explicit that we prefer hosted over build-yourself, and that ongoing maintenance must be minimal.

Splitting the services hands supervision to Railway entirely. It is the option where we own the least.

### Secondary benefits

These are real but would not on their own justify the work:

- **Independent restarts and resource limits.** An SSR memory leak stops being able to starve Django.
- **Independent rollback.** A bad frontend deploy can be reverted without also reverting backend code that was fine.
- **The shell entrypoint goes away.** It currently runs as PID 1 and leaves zombie processes.

## What the split would look like

Four services rather than the current two:

```text
Bunny CDN → Caddy service (public domain)
              ├─ /api/*, /djadmin/*, /static/*, /media/*  → Django service   (private network)
              └─ /*                                        → SSR service     (private network)
            Postgres service (unchanged)
```

Caddy keeps the public origin and its existing routing. Django and SSR become private services reachable over Railway's internal network. `INTERNAL_API_BASE_URL` moves from Caddy's loopback listener to the Django service's private hostname — which would reintroduce the crash in [#726](https://github.com/The-Flip/flipcommons/issues/726), since it puts Node straight in front of Gunicorn's connection-closing sync worker again. A split has to keep SSR's API calls flowing through Caddy, or move Django to a keep-alive worker class.

### Caddy has to stay a service

Railway has no path-based routing across services on one domain. Nothing at the platform level can send `/api/*` to one service and `/*` to another, so the fan-out has to run inside a service we control. This is a constraint we are working around, not a design preference — and it is why "let Railway manage them independently" does not mean "delete Caddy".

## Costs and risks

### Same-origin is load-bearing

This is the risk that makes a naive split much bigger than it looks.

[Architecture.md](../../Architecture.md#same-origin-model) documents a same-origin model in both dev and production: Django session cookies, no JWT, no CORS, and a CSRF contract where the frontend reads the `csrftoken` cookie and returns it as `X-CSRFToken`. Django admin and the user-facing app share one auth authority. All of that works because Caddy makes Django and SSR a single origin to the browser.

A split that keeps Caddy in front preserves this exactly — the browser still sees one hostname and nothing about auth changes. A split that instead gives Django its own public domain is not an infrastructure refactor; it is a cross-site cookie and CORS migration, and it should be understood as a different, much larger project.

The Bunny apex pull zone reinforces the same conclusion. It fronts one origin hostname and carries an `X-Origin-Auth` shared secret plus an `X-Client-IP` edge rule that [`Caddyfile`](../../../Caddyfile) validates before promoting the client IP that rate limiting depends on (see [ClientIpTrust.md](ClientIpTrust.md)). That contract is between Bunny and a single origin.

### Deploy lockstep is lost

One image today means the frontend and backend are always the same commit. `schema.d.ts` is generated from the backend schema at build time, so the typed client and the API it calls cannot drift.

Independent services deploy independently. There will be windows — short, but real — where the SSR service is running against an API of a different vintage. That is normal for split deployments and manageable with additive-first API changes, but it is new surface we do not have today, and it interacts with the migration-ordering question above.

### Cost

Unresolved, and potentially decisive given [SmallTeam.md](../../SmallTeam.md). See [Open questions](#open-questions).

### More moving parts to onboard

A new contributor currently reads one Dockerfile and one entrypoint. Four services means four deploy targets, private-network hostnames to know about and per-service environment variables to keep in sync. This cuts directly against "a new contributor should be productive on day one".

Local development is unaffected either way — Vite proxies to Django and nothing about the split changes that.

## Alternatives considered

### s6-overlay in one container

Adopt a real init system inside the existing container. It supervises and restarts each process independently and reaps the zombies the current shell entrypoint leaves behind.

Keeps one service, one bill, one deploy unit and one origin — every cost in the section above disappears. The trade is that we own an init system and its configuration, which is the "build-yourself" side of a principle we have chosen not to be on. Worth pricing against the split rather than dismissing.

### Hand-rolled restart logic in the entrypoint

Rejected. Covered under [Supervision is the platform's job](#supervision-is-the-platforms-job).

### Do nothing

The status quo is defensible if SSR crashes stop happening — the supervision design only hurts when a process dies. But it makes site availability contingent on the least stable process in the container, and [#726](https://github.com/The-Flip/flipcommons/issues/726) is a reminder that a single unpatched upstream bug in any one of the three is enough.

## Not a motivation

**Scale.** Nothing here is driven by traffic or load. The single container is not resource-constrained and there is no scaling pressure. This is entirely about fault isolation and about which supervision problems we own.
