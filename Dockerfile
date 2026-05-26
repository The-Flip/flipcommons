# Multi-stage build: SvelteKit frontend + Django backend
# Used by Railway for the single production service

# ── Stage 1: Build SvelteKit frontend ──────────────────────────────
FROM node:24-slim AS frontend-build

# node:*-slim variants ship without ca-certificates. Node's own HTTPS uses
# its bundled CA roots and works fine, but tools that shell out to the OS
# trust store (notably sentry-cli, invoked by sentrySvelteKit during
# sourcemap upload) fail TLS verification with "unable to get local issuer
# certificate" against ingest endpoints. Install ca-certificates so any
# such tool can reach the public internet over HTTPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable

WORKDIR /frontend

# Install dependencies (cached layer)
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source and build. RAILWAY_GIT_COMMIT_SHA is auto-injected by Railway
# for GitHub-triggered deploys; it stamps the SvelteKit build version so open
# browser tabs can detect a new deploy via version.json polling. Outside
# Railway the ARG falls back to "dev" and polling is disabled.
ARG RAILWAY_GIT_COMMIT_SHA=dev
ENV RAILWAY_GIT_COMMIT_SHA=$RAILWAY_GIT_COMMIT_SHA

# Sentry sourcemap upload happens during `pnpm build` (sentrySvelteKit
# plugin). The plugin's autoUploadSourceMaps gate in vite.config.ts is
# truthy only when all three of these are non-empty, so without them the
# build silently skips the upload and browser stack traces stay
# minified in production. Multi-stage Docker doesn't inherit host env
# vars into build stages; Railway passes service-scoped vars as build
# args, but only for ARGs the Dockerfile declares — hence the explicit
# declarations here. Defaults are empty so local/CI Docker builds without
# Sentry secrets still succeed (the upload just no-ops).
ARG SENTRY_AUTH_TOKEN=""
ARG SENTRY_ORG=""
ARG SENTRY_PROJECT=""
ENV SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN \
    SENTRY_ORG=$SENTRY_ORG \
    SENTRY_PROJECT=$SENTRY_PROJECT

# PUBLIC_SENTRY_DSN is consumed at build time by svelte.config.js to
# derive both the CSP report-uri and the connect-src allowlist entry
# for the runtime Sentry SDK. Same Railway-build-arg rule applies as
# above: without an explicit ARG declaration the variable never
# reaches `pnpm build` and the report-only CSP silently degrades to
# nothing (the malformed-DSN guard in svelte.config.js throws if it's
# set but unparseable; an empty value is treated as "unconfigured").
ARG PUBLIC_SENTRY_DSN=""
ENV PUBLIC_SENTRY_DSN=$PUBLIC_SENTRY_DSN

# CDN_URL flips SvelteKit kit.paths.assets so chunks, CSS, fonts, and
# /_app/version.json load from the Bunny pull zone at static.flipcommons.org.
# Same Railway-build-arg rule applies as above: without an explicit ARG
# declaration the variable never reaches `pnpm build` and the production
# build silently falls back to same-origin assets. Empty (the default)
# means same-origin, so local/CI Docker builds without the var still work.
ARG CDN_URL=""
ENV CDN_URL=$CDN_URL

COPY frontend/ .
RUN pnpm build
# Keep only runtime dependencies for the Node SSR server we copy below.
RUN pnpm prune --prod

# ── Stage 2: Runtime dependencies for Caddy + Node ────────────────
FROM node:24-slim AS node-runtime

FROM caddy:2.11.3 AS caddy-runtime

# ── Stage 3: Django + SSR application ──────────────────────────────
FROM python:3.14-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=caddy-runtime /usr/bin/caddy /usr/local/bin/caddy

WORKDIR /app
ENV INTERNAL_API_BASE_URL=http://127.0.0.1:8000

# Install dependencies (cached layer)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY backend/ .

# Copy frontend runtime artifacts from stage 1
COPY --from=frontend-build /frontend/build /app/frontend_runtime/build
COPY --from=frontend-build /frontend/node_modules /app/frontend_runtime/node_modules
COPY --from=frontend-build /frontend/package.json /app/frontend_runtime/package.json

# Reverse-proxy and startup config
COPY Caddyfile /app/Caddyfile
COPY scripts/start-production /app/scripts/start-production
RUN chmod +x /app/scripts/start-production

# Collect static files (Django admin CSS, etc.)
RUN DJANGO_SETTINGS_MODULE=config.settings \
    SECRET_KEY=build-placeholder \
    DEBUG=false \
    uv run python manage.py collectstatic --noinput

EXPOSE 8080

CMD ["/app/scripts/start-production"]
