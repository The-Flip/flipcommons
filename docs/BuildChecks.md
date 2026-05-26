# Build-Phase Checks

This documents how to develop pre-flight build-phase refusal gates. These gates run at build time, in-process, before the new container takes traffic.

## We automate aggressively

These checks are important; we automate agressively. See [DeployAutomation.md](DeployAutomation.md).

## We also have deploy-phase checks

After the build is built, there's a deploy phase where we can do more sophisticated checks on the running services. See [DeployChecks.md](DeployChecks.md).

## Scope

Anything that runs inside the Dockerfile, including `pnpm build` and any other `RUN` step. A non-zero exit at any of these stops the build; Railway refuses to start a container from the broken image, and the previous deploy keeps serving.

## What fails the build for free

These come from Docker / pnpm semantics — we don't have to do anything to get them:

- TypeScript compile errors, missing imports, syntax errors (`pnpm build`)
- Lockfile-out-of-sync (`pnpm install --frozen-lockfile`)
- Any `RUN` step returning non-zero
- Network failures during `apt-get` or `pnpm install`
- A `COPY` from a non-existent path

## What requires explicit wiring

We maintain the following conventions in `Dockerfile` and `frontend/vite.config.ts`.

- **Build-time env vars must be declared as `ARG`s.** Multi-stage Docker does not inherit host env vars into build stages. Railway only passes service variables as build args for `ARG`s the Dockerfile explicitly declares. Currently declared: `RAILWAY_GIT_COMMIT_SHA`, `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT`, `PUBLIC_SENTRY_DSN`, `CDN_URL`. Adding a new build-time env var is a two-step change (declare in `Dockerfile`, set on Railway service); skipping either silently turns the consumer into a no-op.
- **`ca-certificates` must be installed in the frontend-build stage.** The `node:*-slim` base ships without OS CA roots. Node's own HTTPS bundles its own CA list and works fine, but tools that shell out to the OS trust store — notably sentry-cli, used by `sentrySvelteKit` for sourcemap upload — fail with `unable to get local issuer certificate`.
