import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { NARROW_BREAKPOINT, WIDE_BREAKPOINT } from './src/lib/breakpoints.js';

// Inject @custom-media declarations into every component <style> block so
// postcss-custom-media (which sees each block in isolation) can resolve
// `(--breakpoint-*)` references. Kept on a single line so error line
// numbers in component <style> blocks aren't shifted by the injection.
const SHARED_CUSTOM_MEDIA =
  `@custom-media --breakpoint-narrow (max-width: ${NARROW_BREAKPOINT}rem);` +
  ` @custom-media --breakpoint-wide (min-width: ${WIDE_BREAKPOINT}rem); `;

const injectCustomMedia = {
  name: 'inject-custom-media',
  style: ({ content }) => ({ code: SHARED_CUSTOM_MEDIA + content }),
};

// Parse the Sentry DSN to derive both the CSP report endpoint AND the
// connect-src host the runtime SDK will POST events to. Both must point
// at exactly the deployed project's region — Sentry SaaS now uses
// regional ingest hosts like `o<org>.ingest.us.sentry.io` and
// `o<org>.ingest.de.sentry.io`, which a wildcard like `*.ingest.sentry.io`
// would NOT match (the CSP host wildcard only spans the one label).
//
// Returns null when the DSN is unset (dev, CI, preview); in that case
// the report-uri directive is omitted below — the policy is still
// enforced, there is just nowhere to report violations — and the
// Sentry connect-src entry is omitted (the runtime SDK is also inert
// without a DSN, so no traffic to allowlist).
//
// When the DSN IS set but malformed, we throw rather than return null.
// Silent fallback would leave prod enforcing a policy whose violations
// go nowhere, with no log line; failing the config load surfaces the
// typo at deploy time instead.
//
// DSN:    https://<key>@<host>/<project>
// Report: https://<host>/api/<project>/security/?sentry_key=<key>
// Origin: https://<host>
function parseSentryDsn(dsn) {
  if (!dsn) return null;
  let u;
  try {
    u = new URL(dsn);
  } catch (err) {
    throw new Error(`PUBLIC_SENTRY_DSN is not a valid URL: ${err.message}`);
  }
  const project = u.pathname.replace(/^\//, '');
  if (!u.username || !project) {
    throw new Error(
      `PUBLIC_SENTRY_DSN is malformed: expected https://<key>@<host>/<project>, got ${dsn}`,
    );
  }
  return {
    reportUri: `${u.protocol}//${u.host}/api/${project}/security/?sentry_key=${u.username}`,
    origin: u.origin,
  };
}

const sentry = parseSentryDsn(process.env.PUBLIC_SENTRY_DSN);
const sentryCspReportUri = sentry?.reportUri ?? null;
const sentryOrigin = sentry?.origin ?? null;

// Railway stamps RAILWAY_GIT_COMMIT_SHA on real builds. The Dockerfile sets it
// to the literal "dev" outside Railway, so truthiness alone would read a local
// Docker build as a deploy; the SITE_ORIGIN guard below and kit.version share
// this one signal so "is this Railway?" is defined in one place.
const isRailwayBuild =
  !!process.env.RAILWAY_GIT_COMMIT_SHA && process.env.RAILWAY_GIT_COMMIT_SHA !== 'dev';

// SITE_ORIGIN feeds prerender.origin (baked into the canonical href and OG
// tags on prerendered routes) and — once /sitemap.xml ships — the sitemap
// URLs and the robots.txt `Sitemap:` line. The svelte.config.js fallback
// below (`'http://localhost:5173'`) is fine for `make dev`, but a Railway
// build with the var unset would silently bake localhost URLs into every
// prerendered HTML file. Fail-closed in Railway builds; the matching
// deploy-time check (`apps/core/checks.py:check_site_origin`, error ids
// core.E303 / E304) catches the case where the var drifted between build
// and deploy.
const rawSiteOrigin = process.env.SITE_ORIGIN?.trim() ?? '';
if (isRailwayBuild && !rawSiteOrigin) {
  throw new Error(
    'SITE_ORIGIN is required in Railway builds. Set SITE_ORIGIN=https://<host> ' +
      '(production is https://flipcommons.org) so prerendered canonical URLs, ' +
      'OG tags, and the sitemap point at the real origin.',
  );
}
// SITE_ORIGIN is string-concatenated with paths to build canonical
// URLs and the sitemap Sitemap: line — a stray query or fragment in the
// origin would produce broken URLs downstream. Stays in lockstep with the
// deploy-time `_is_valid_site_origin()` check in apps/core/checks.py.
if (rawSiteOrigin && !/^https:\/\/[^/?#]+$/.test(rawSiteOrigin)) {
  throw new Error(
    `SITE_ORIGIN must be an https:// origin with no path, trailing slash, ` +
      `query string, or fragment (e.g. https://flipcommons.org). Got: ` +
      `${JSON.stringify(rawSiteOrigin)}`,
  );
}

// Hash the inline <style> block in app.html so it survives an enforced
// `style-src 'self'`. SvelteKit only auto-hashes inline styles it injects
// itself (bundler-inlined CSS, sub-threshold component styles) — the
// hand-written <style> in app.html is part of the template and is
// invisible to SvelteKit's hasher. Recomputing the hash on every config
// load means prettier or hand edits to that block can never silently
// drift from CSP; the next dev server start (or build) picks up the new
// bytes. If the <style> block ever disappears from app.html we throw
// rather than emit a stale or empty hash.
function computeAppHtmlStyleHash() {
  const appHtml = readFileSync(new URL('./src/app.html', import.meta.url), 'utf8');
  const match = appHtml.match(/<style>([\s\S]*?)<\/style>/);
  if (!match) {
    throw new Error('app.html no longer contains a <style> block — update svelte.config.js CSP.');
  }
  return `sha256-${createHash('sha256').update(match[1]).digest('base64')}`;
}

const appHtmlStyleHash = computeAppHtmlStyleHash();

// CSP directives. Notes on the non-obvious choices:
//   - `script-src 'self'` + SvelteKit's per-page hash/nonce (mode: 'auto')
//     covers the bundled JS and SvelteKit's inline hydration script.
//     PostHog and Sentry SDKs ship in the bundle (`npm install`), not via
//     CDN, so no third-party host is needed in script-src.
//   - `style-src 'self'` plus an explicit sha256 of app.html's inline
//     <style> block (see computeAppHtmlStyleHash). SvelteKit's hash/
//     nonce machinery only covers styles it injects itself; hand-written
//     <style> in the app.html template is invisible to it, so the hash
//     has to be added by hand. SvelteKit hashes its own injected inline
//     styles in prerendered pages and nonces them in SSR'd pages. This
//     strict form is report-only — see cspStyleReportOnlyDirectives.
//   - `img-src 'self' https: data:` is intentionally permissive. Catalog
//     images come from img.opdb.org, media.flipcommons.org, and other
//     hosts surfaced by ingest pipelines; locking img-src to a fixed list
//     fails loudly the first time a new host appears, and <img> tags
//     have negligible XSS surface.
//   - `connect-src` is the Sentry origin derived from PUBLIC_SENTRY_DSN
//     (so regional DSNs like o12345.ingest.us.sentry.io are handled
//     correctly — a wildcard like `*.ingest.sentry.io` would NOT match
//     those) plus PostHog's api_host. PostHog's external chunk loads
//     (session-recording.js, surveys.js, /flags) are all disabled in
//     lib/analytics/config.ts — us.i.posthog.com (the dedicated US
//     ingestion subdomain that PostHog recommends as api_host) is the
//     only host the SDK actually contacts. When no DSN is configured the Sentry
//     entry is omitted; the runtime SDK is also inert in that case.
//   - `frame-ancestors 'none'` prevents other origins from framing us
//     (the modern equivalent of X-Frame-Options: DENY in Caddyfile, kept
//     for old browsers). `frame-src 'none'` because we don't embed
//     anything ourselves.
//   - report-uri (not report-to) because Sentry's documented CSP endpoint
//     uses the older format and browser support for report-to is uneven.
//   - `upgrade-insecure-requests` is added in the enforced block below
//     rather than here, because it is a navigation directive rather than
//     a fetch directive and only applies to production builds — it
//     upgrades http:// subresource URLs to https://, which our code
//     already uses everywhere, but breaks plain-HTTP localhost.
const cspFetchDirectives = {
  'default-src': ['self'],
  // jsdelivr/@scalar: the /api-docs page loads the @scalar/api-reference
  // bundle from jsdelivr; it also dynamically imports further chunks, so
  // the host needs to be in connect-src too. Scoped to the @scalar org
  // path (trailing slash = prefix match) to cover versioned chunks while
  // excluding the rest of the CDN.
  'script-src': ['self', 'https://cdn.jsdelivr.net/npm/@scalar/'],
  // style-src is deliberately permissive in the ENFORCED policy and
  // strict in the report-only one below. It cannot simply be omitted:
  // `default-src 'self'` would then act as its fallback and enforce it.
  'style-src': ['self', 'unsafe-inline'],
  // Svelte's `style:` directive (and any hand-written `style="..."`
  // attribute) compiles to an inline style attribute, which CSP gates
  // separately under style-src-attr. Without this entry the browser
  // falls back to style-src — which doesn't permit attribute styles
  // even with hashes — and every page with e.g. SiteHeader's dynamic
  // SVG-filter id breaks. style-src-attr is much lower
  // risk than style-src-elem (an attacker can restyle but can't load
  // a remote stylesheet or inject a <style> block), so 'unsafe-inline'
  // here is the standard compromise for Svelte/React apps.
  'style-src-attr': ['unsafe-inline'],
  'img-src': ['self', 'https:', 'data:'],
  // fonts.scalar.com: the @scalar/api-reference widget on /api-docs loads
  // its own Inter webfonts (incl. inter-greek.woff2) from there, even
  // though we override --scalar-font. Allow it so the fetch isn't blocked.
  'font-src': ['self', 'https://fonts.scalar.com'],
  // api.scalar.com: the @scalar/api-reference widget queries its own API
  // registry (/vector/registry/curated and /search) on the /api-docs page.
  // Nothing we serve depends on it, but blocking it logs console errors
  // for every visitor to that page.
  'connect-src': [
    'self',
    ...(sentryOrigin ? [sentryOrigin] : []),
    'https://us.i.posthog.com',
    'https://cdn.jsdelivr.net/npm/@scalar/',
    'https://api.scalar.com',
  ],
  'frame-ancestors': ['none'],
  'frame-src': ['none'],
  'object-src': ['none'],
  'base-uri': ['self'],
  'form-action': ['self'],
  ...(sentryCspReportUri ? { 'report-uri': [sentryCspReportUri] } : {}),
};

// style-src is the one directive still in report-only, in its own policy
// alongside the enforced one above. Enforcing `style-src 'self' <hash>`
// breaks /api-docs: the @scalar/api-reference widget injects <style>
// elements at runtime whose contents vary by widget version (one of them
// is even empty), so no build-time hash can cover them and the page
// renders unstyled. Keeping the strict version report-only means Sentry
// still shows what a strict style-src would have blocked, without
// shipping a broken docs page. Promoting it means moving these two
// entries into cspFetchDirectives, replacing the permissive style-src
// there, and re-checking /api-docs.
//
// Only attached when a Sentry report destination is configured:
// SvelteKit throws at request time if a report-only header is set with
// no report-to/report-uri directive, so in dev/CI/preview (no DSN) the
// block is dropped — there is nowhere to send reports anyway. The policy
// deliberately omits default-src, so it checks style-src and nothing else.
const cspStyleReportOnlyDirectives = {
  'style-src': ['self', appHtmlStyleHash],
  'style-src-attr': ['unsafe-inline'],
  'report-uri': [sentryCspReportUri],
};

// The policy is enforced in production builds only. Two reasons dev is
// exempt. `upgrade-insecure-requests` rewrites every http:// request to
// https://, which is correct for the HTTPS-only site but breaks the dev
// server and `vite preview` — both run plain HTTP on localhost, and
// browsers that honor the directive (Safari, Chromium) upgrade the
// top-level navigation to https://localhost:5173, where nothing is
// listening, and fail with "can't establish a secure connection."
// (Firefox exempts localhost so it slips through.) And Vite's dev-time
// HMR client injects inline scripts and styles that the production
// hashes and nonces don't cover. Dev gets no CSP at all, matching
// pre-CSP behavior locally; `make build` is what exercises the policy.
const isProductionBuild = process.env.NODE_ENV === 'production';
const cspEnforcedDirectives = isProductionBuild
  ? { ...cspFetchDirectives, 'upgrade-insecure-requests': true }
  : {};

/** @type {import('@sveltejs/kit').Config} */
const config = {
  compilerOptions: {
    runes: true,
  },
  preprocess: [injectCustomMedia, vitePreprocess()],
  kit: {
    adapter: adapter(),
    // Two policies ship: the enforced one, and a report-only one
    // carrying the strict style-src that /api-docs can't satisfy yet.
    // mode:'auto' uses hashes for prerendered pages and nonces for SSR'd
    // ones, both of which cover SvelteKit's hydration script and the
    // inline <style> in app.html; the hand-written app.html <style> also
    // needs the explicit sha256 above, which SvelteKit's hasher can't see.
    //
    // Violations report via `report-uri`, in both policies, whenever a
    // Sentry DSN is configured. Two caveats on what that catches.
    // Prerendered routes (`export const prerender = true`: /api-docs and
    // the three /(legal)/* pages) carry their CSP in a <meta http-equiv>
    // tag rather than a response header, and browsers both ignore
    // report-uri in meta and reject the Report-Only variant there — so
    // those four routes enforce the policy but report nothing, and never
    // see the strict style-src at all. And extensions inject into pages
    // constantly, so a violation whose `source_file` is not the document
    // itself is client-side noise, not a fault in this policy.
    csp: {
      mode: 'auto',
      directives: cspEnforcedDirectives,
      ...(sentryCspReportUri ? { reportOnly: cspStyleReportOnlyDirectives } : {}),
    },
    experimental: {
      // Required by @sentry/sveltekit >= 10.8.0: SvelteKit loads
      // src/instrumentation.server.ts before any other server import,
      // which is the only load-order-safe init site for the OpenTelemetry-
      // powered server SDK. Without this flag, Sentry.init runs too late.
      instrumentation: { server: true },
    },
    version: {
      name: isRailwayBuild ? process.env.RAILWAY_GIT_COMMIT_SHA : 'dev',
      // Only poll when a real SHA is stamped (production builds). In dev the
      // version stays 'dev' forever, so polling would just be noise.
      pollInterval: isRailwayBuild ? 60 * 60 * 1000 : 0,
    },
    prerender: {
      origin: rawSiteOrigin || 'http://localhost:5173',
      handleHttpError: ({ path, message }) => {
        // API endpoints are served by Django, not SvelteKit — ignore
        // them when the prerender crawler discovers <link rel="preload">
        // hints in prerendered pages.
        if (path.startsWith('/api/')) return;
        throw new Error(message);
      },
    },
  },
};

export default config;
