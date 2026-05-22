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
// the reportOnly block is skipped entirely below — SvelteKit refuses to
// emit a report-only CSP header without a report destination — and the
// Sentry connect-src entry is omitted (the runtime SDK is also inert
// without a DSN, so no traffic to allowlist).
//
// When the DSN IS set but malformed, we throw rather than return null.
// Silent fallback would downgrade prod from "report-only CSP" to "no
// CSP at all" with no log line; failing the config load surfaces the
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

// Production deploys serve SvelteKit-emitted asset URLs through a CDN
// pull zone (currently a Bunny zone at https://static.flipcommons.org;
// CDN_URL accepts any https origin to allow swapping providers or
// testing against an alternate zone). When set, paths.assets rewrites
// the references SvelteKit itself emits — entry script and modulepreload
// tags, bundled CSS links, %sveltekit.assets% placeholders in app.html,
// the /_app/version.json poll, and url() refs inside hashed CSS that
// resolve relative to the CSS file's URL. Hand-written URLs in component
// markup (e.g. `<img src="/og-default.png">`) are NOT rewritten — they
// stay on origin unless threaded through the `assets` helper from
// $app/paths. Local dev and CI leave CDN_URL unset; Vite's dev server
// would otherwise emit CDN URLs for chunks that only exist locally. See
// docs/plans/perf/StaticAssetCDN.md.
//
// Three valid states:
//   - "https://host"  → CDN enabled
//   - "DISABLED"      → CDN explicitly off (rollback path; also the
//                       right value for Railway preview deploys that
//                       inherit RAILWAY_GIT_COMMIT_SHA but shouldn't
//                       route through production's CDN)
//   - unset / empty   → CDN off locally; ERROR in Railway builds
//                       (fail-closed per docs/Reviewing.md, so a
//                       forgotten env var doesn't silently ship
//                       same-origin assets)
const rawCdn = process.env.CDN_URL?.trim() ?? '';
const isRailwayBuild =
  !!process.env.RAILWAY_GIT_COMMIT_SHA && process.env.RAILWAY_GIT_COMMIT_SHA !== 'dev';
if (isRailwayBuild && !rawCdn) {
  throw new Error(
    'CDN_URL is required in Railway builds. Set CDN_URL=https://<host> (production ' +
      'is https://static.flipcommons.org) to enable the CDN, or CDN_URL=DISABLED to ' +
      'explicitly opt out (rollback path, or preview deploys). See ' +
      'docs/plans/perf/StaticAssetCDN.md.',
  );
}
const cdnUrl = rawCdn && rawCdn !== 'DISABLED' ? rawCdn : null;
if (cdnUrl && !/^https:\/\/[^/]+$/.test(cdnUrl)) {
  throw new Error(
    `CDN_URL must be an https:// origin with no path or trailing slash (e.g. ` +
      `https://static.flipcommons.org). Got: ${JSON.stringify(cdnUrl)}`,
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
//     styles in prerendered pages and nonces them in SSR'd pages.
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
//     lib/analytics/config.ts — us.posthog.com is the only host the
//     SDK actually contacts. When no DSN is configured the Sentry
//     entry is omitted; the runtime SDK is also inert in that case.
//   - `frame-ancestors 'none'` prevents other origins from framing us
//     (the modern equivalent of X-Frame-Options: DENY in Caddyfile, kept
//     for old browsers). `frame-src 'none'` because we don't embed
//     anything ourselves.
//   - report-uri (not report-to) because Sentry's documented CSP endpoint
//     uses the older format and browser support for report-to is uneven.
//   - `upgrade-insecure-requests` is split into the enforced block below
//     because the directive is ignored in report-only mode (per spec) and
//     it's safe to enforce on day one — it just upgrades http:// sub-
//     resource URLs to https://, which our code already uses everywhere.
// CDN host appears in script-/style-/font-/connect-src because flipping
// kit.paths.assets routes the chunk, CSS, @font-face url(), and the
// hourly /_app/version.json fetch through the CDN origin. img-src is
// already permissive enough (https:) to cover CDN-hosted images.
const cdnEntry = cdnUrl ? [cdnUrl] : [];
const cspReportOnlyDirectives = {
  'default-src': ['self'],
  'script-src': ['self', ...cdnEntry],
  'style-src': ['self', appHtmlStyleHash, ...cdnEntry],
  'img-src': ['self', 'https:', 'data:'],
  'font-src': ['self', ...cdnEntry],
  'connect-src': [
    'self',
    ...cdnEntry,
    ...(sentryOrigin ? [sentryOrigin] : []),
    'https://us.posthog.com',
  ],
  'frame-ancestors': ['none'],
  'frame-src': ['none'],
  'object-src': ['none'],
  'base-uri': ['self'],
  'form-action': ['self'],
  ...(sentryCspReportUri ? { 'report-uri': [sentryCspReportUri] } : {}),
};

const cspEnforcedDirectives = {
  'upgrade-insecure-requests': true,
};

/** @type {import('@sveltejs/kit').Config} */
const config = {
  compilerOptions: {
    runes: true,
  },
  preprocess: [injectCustomMedia, vitePreprocess()],
  kit: {
    adapter: adapter(),
    // CDN-fronted asset URLs (production only). paths.relative MUST be
    // false when paths.assets is set; SvelteKit then emits absolute URLs
    // for every asset reference in SSR'd HTML. Dropped entirely when
    // CDN_URL is unset so local dev keeps same-origin asset loading.
    ...(cdnUrl ? { paths: { assets: cdnUrl, relative: false } } : {}),
    // Initial CSP rollout is report-only for the fetch directives:
    // browsers send violation reports to Sentry but nothing is blocked.
    // `upgrade-insecure-requests` is enforced from day one (see comment
    // on cspEnforcedDirectives). Once Sentry shows zero reports from
    // real traffic for ~a week, fold cspReportOnlyDirectives into
    // `directives` to enforce. Tracked in issue #448. mode:'auto' uses
    // hashes for prerendered pages and nonces for SSR'd ones, both of
    // which cover SvelteKit's hydration script and the inline <style>
    // in app.html.
    //
    // KNOWN GAP — report-only does NOT cover prerendered routes.
    // SvelteKit can only deliver Content-Security-Policy-Report-Only as
    // an HTTP response header (see csp.js / render.js), and prerendered
    // routes are served as static HTML files where the CSP is baked
    // into a <meta http-equiv> tag — and the CSP spec disallows the
    // Report-Only variant in meta. So routes with `export const
    // prerender = true` (currently /systems, /series, /reward-types,
    // /gameplay-features, /people, /search, /api-docs, /(legal)/terms,
    // /(legal)/privacy, /(legal)/licensing) will produce zero reports
    // regardless of violations. Before flipping to enforce, build with
    // the report-only directives moved to `directives` and smoke-test
    // those prerendered routes locally. The week-of-clean-reports gate
    // applies to SSR'd routes only.
    //
    // `reportOnly` is only attached when a Sentry report destination is
    // configured. SvelteKit throws at request time if a report-only
    // header is set without a report-to/report-uri directive, so in dev/
    // CI/preview (no DSN) we drop the block entirely — there's nowhere
    // for the browser to send reports anyway.
    csp: {
      mode: 'auto',
      directives: cspEnforcedDirectives,
      ...(sentryCspReportUri ? { reportOnly: cspReportOnlyDirectives } : {}),
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
      // version stays 'dev' forever, so polling would just be noise. The
      // Dockerfile sets RAILWAY_GIT_COMMIT_SHA to the literal "dev" outside
      // Railway, so checking truthiness alone would (wrongly) enable polling
      // for local Docker builds — share the isRailwayBuild signal with the
      // CDN_URL guard above to keep "is this Railway?" defined in one place.
      pollInterval: isRailwayBuild ? 60 * 60 * 1000 : 0,
    },
    prerender: {
      origin: process.env.SITE_ORIGIN || 'http://localhost:5173',
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
