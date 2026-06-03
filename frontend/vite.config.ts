import { defineConfig } from 'vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { sentrySvelteKit } from '@sentry/sveltekit';

// Mirror Railway's commit SHA into the PUBLIC_ namespace for the duration
// of this build, so any consumer using `$env/static/public` (e.g. inlined
// release tags) gets the same value the sourcemap upload below uses.
// hooks.client.ts intentionally reads `$env/dynamic/public` — that's a
// runtime lookup against the Node SSR process, not this build process,
// so the matching mirror for the browser/SSR runtime lives in
// scripts/start-production. ??= leaves an explicitly-set value alone.
process.env.PUBLIC_RAILWAY_GIT_COMMIT_SHA ??= process.env.RAILWAY_GIT_COMMIT_SHA;

export default defineConfig({
  plugins: [
    // sentrySvelteKit MUST come before sveltekit(), per Sentry docs.
    sentrySvelteKit({
      // Explicit upload gate: only attempt upload when all three secrets
      // are present (local dev, CI, no-secrets builds skip cleanly).
      // Makes the no-op behavior explicit instead of relying on plugin
      // internals to silently no-op when SENTRY_AUTH_TOKEN is missing.
      autoUploadSourceMaps:
        !!process.env.SENTRY_AUTH_TOKEN && !!process.env.SENTRY_ORG && !!process.env.SENTRY_PROJECT,
      telemetry: false,
      org: process.env.SENTRY_ORG,
      project: process.env.SENTRY_PROJECT,
      authToken: process.env.SENTRY_AUTH_TOKEN,
      release: { name: process.env.RAILWAY_GIT_COMMIT_SHA, inject: true },
      sourcemaps: {
        // Plugin doesn't delete maps by default. Delete after upload so
        // they don't ship to browsers.
        filesToDeleteAfterUpload: ['./.svelte-kit/**/*.map', './build/**/*.map'],
      },
    }),
    sveltekit(),
  ],
  build: {
    rollupOptions: {
      output: {
        // Vendor-split third-party libs into their own chunks so app deploys
        // don't invalidate cached vendor bytes. Sentry and PostHog are loaded
        // eagerly from the root layout (Sentry via hooks.client.ts; PostHog via
        // the side-effect import of $lib/analytics in +layout.svelte), so without
        // this they'd land in the layout chunk whose hash changes on every app
        // deploy — re-downloading ~150 KB gzipped of unchanged SDK code each time.
        // @floating-ui/dom is shared by the filter-sidebar/menu components and
        // Rollup already auto-splits it, but pinning it here keeps that isolation
        // immune to import-graph shifts (a static import, unlike the old dynamic
        // one, doesn't force a chunk boundary on its own). Separate chunks (rather
        // than one combined "vendor") because the libs version independently;
        // HTTP/2/3 multiplexing makes the extra request cost negligible.
        manualChunks: (id) => {
          if (id.includes('/posthog-js/')) return 'vendor-posthog';
          if (id.includes('/@sentry/')) return 'vendor-sentry';
          if (id.includes('/@floating-ui/')) return 'vendor-floating-ui';
        },
      },
    },
  },
  server: {
    proxy: {
      '/api/': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/djadmin': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/media/': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/static/': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
