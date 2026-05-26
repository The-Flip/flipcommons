import type { PostHogConfig } from 'posthog-js';
// Type-only import — the lint rule allows this via `allowTypeImports`.
// `config.ts` ships no runtime reference to the SDK.

// Locked-down PostHog init options. Each option here is a contract — the
// integration test asserts the value, and weakening any of them fails the
// test. See docs/Analytics.md § Privacy posture for the contract this
// enforces.
export const config: Partial<PostHogConfig> = {
  api_host: 'https://us.i.posthog.com',
  persistence: 'memory', // satisfies "no persistent client-side identity"
  autocapture: false, // satisfies "no autocapture / implicit tracking"
  capture_pageview: 'history_change', // SPA-aware: initial load + every CSR navigation
  capture_pageleave: 'if_capture_pageview',
  disable_session_recording: true,
  disable_surveys: true,
  // Stop the SDK from fetching session-recording.js, surveys.js, etc. at runtime.
  disable_external_dependency_loading: true,
  // Stop the SDK from POSTing to /flags for remote feature-flag / decide config.
  // `disable_external_dependency_loading` does NOT cover this — it only gates
  // external <script> loads. The flag fetch is a separate XHR controlled by
  // `advanced_disable_flags` (current name; replaces deprecated
  // `advanced_disable_decide`). Without this, every $pageview from a fresh
  // SPA instance also triggers a /flags request even though we never read
  // feature flags. Satisfies "feature-flag SDK unused" in the architecture.
  advanced_disable_flags: true,
  // PostHog defaults to extracting utm_*, gclid, fbclid, msclkid, gbraid,
  // wbraid, li_fat_id, etc. from the landing URL and storing them as top-level
  // event properties. Our scrub of `$current_url` doesn't reach those — they
  // ship as separate props. Disable the extractor entirely.
  save_campaign_params: false,

  // satisfies "no IP-based attribution"
  ip: false,
  property_denylist: [
    '$ip', // belt-and-suspenders alongside ip: false
    '$screen_height', // satisfies "no fingerprinting-grade properties"
    '$screen_width',
    '$viewport_height',
    '$viewport_width',
    // PostHog detects search-engine referrers (google/bing/yahoo/duckduckgo)
    // and surfaces the search query as `ph_keyword` plus `$search_engine`.
    // There's no config flag to disable that path; denylisting them at send
    // time is the documented mitigation.
    'ph_keyword',
    '$search_engine',
  ],

  // Strip query strings from URLs before send — bounds cardinality and keeps
  // query-encoded search terms / state out of the firehose. `$pathname` and
  // `$current_url` are PostHog-set; `$prev_pageview_pathname` is populated
  // automatically when capture_pageview is on; `$referrer` carries the
  // external referring document's full URL including any query string the
  // referrer chose to send (search-result URLs typically include the query).
  before_send: (event) => {
    if (!event || !event.properties) return event;
    const props = event.properties;
    for (const key of ['$current_url', '$referrer'] as const) {
      const v = props[key];
      if (typeof v === 'string' && URL.canParse(v)) {
        const u = new URL(v);
        props[key] = u.origin + u.pathname;
      }
    }
    for (const key of ['$pathname', '$prev_pageview_pathname'] as const) {
      const v = props[key];
      if (typeof v === 'string') {
        const q = v.indexOf('?');
        if (q !== -1) props[key] = v.slice(0, q);
      }
    }
    return event;
  },
};
