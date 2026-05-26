import { describe, expect, it } from 'vitest';

import { config } from './config';

// Integration test for the locked-down PostHog init config. Each option below
// is a contract — weakening any option fails this test, which is the point.
describe('analytics config (locked-down PostHog init)', () => {
  it('uses the US API host', () => {
    expect(config.api_host).toBe('https://us.i.posthog.com');
  });

  it('uses heap-only persistence (no cookies, no storage)', () => {
    expect(config.persistence).toBe('memory');
  });

  it('disables autocapture', () => {
    expect(config.autocapture).toBe(false);
  });

  it('enables SPA-aware pageview tracking', () => {
    expect(config.capture_pageview).toBe('history_change');
    expect(config.capture_pageleave).toBe('if_capture_pageview');
  });

  it('disables session recording, surveys, and external script loading', () => {
    expect(config.disable_session_recording).toBe(true);
    expect(config.disable_surveys).toBe(true);
    expect(config.disable_external_dependency_loading).toBe(true);
  });

  it('disables /flags remote-config fetching', () => {
    // `disable_external_dependency_loading` only gates external script loads;
    // the feature-flag/decide HTTP request is controlled separately by
    // `advanced_disable_flags`. Both must be set to fully suppress runtime
    // calls to PostHog's flag endpoints.
    expect(config.advanced_disable_flags).toBe(true);
  });

  it('disables campaign-param extraction (utm_*, gclid, fbclid, …)', () => {
    // PostHog defaults to extracting query-string campaign params (utm_*,
    // gclid, fbclid, msclkid, gbraid, wbraid, li_fat_id, ttclid, etc.) and
    // surfacing them as top-level event properties. Our $current_url scrub
    // strips the URL itself but doesn't reach those props — disable the
    // extractor at the source.
    expect(config.save_campaign_params).toBe(false);
  });

  it('strips IP at ingest', () => {
    expect(config.ip).toBe(false);
  });

  it('denylists fingerprinting-grade and search-extracted properties', () => {
    expect(config.property_denylist).toEqual([
      '$ip',
      '$screen_height',
      '$screen_width',
      '$viewport_height',
      '$viewport_width',
      // PostHog auto-extracts these from search-engine referrers and there's
      // no config flag to disable that path. Denylisting at send is the fix.
      'ph_keyword',
      '$search_engine',
    ]);
  });

  describe('before_send query-string scrub', () => {
    const callBeforeSend = (properties: Record<string, unknown>) => {
      const before_send = config.before_send;
      if (typeof before_send !== 'function') {
        throw new Error('before_send must be a function');
      }
      const event = {
        uuid: 'test-uuid',
        event: '$pageview',
        properties,
      };
      return before_send(event);
    };

    it('strips query strings from $current_url, $referrer, $pathname, and $prev_pageview_pathname', () => {
      const result = callBeforeSend({
        $current_url: 'https://example.com/search?q=secret&page=2',
        $referrer: 'https://www.google.com/search?q=our-private-keyword',
        $pathname: '/search?q=secret',
        $prev_pageview_pathname: '/prior?ref=external',
      });

      expect(result?.properties.$current_url).toBe('https://example.com/search');
      expect(result?.properties.$referrer).toBe('https://www.google.com/search');
      expect(result?.properties.$pathname).toBe('/search');
      expect(result?.properties.$prev_pageview_pathname).toBe('/prior');
    });

    it('passes through URLs without query strings unchanged', () => {
      const result = callBeforeSend({
        $current_url: 'https://example.com/about',
        $pathname: '/about',
      });

      expect(result?.properties.$current_url).toBe('https://example.com/about');
      expect(result?.properties.$pathname).toBe('/about');
    });

    it('leaves a malformed $current_url alone instead of throwing', () => {
      const result = callBeforeSend({ $current_url: 'not a url' });
      expect(result?.properties.$current_url).toBe('not a url');
    });

    it('leaves a malformed $referrer alone instead of throwing', () => {
      const result = callBeforeSend({ $referrer: 'not a url' });
      expect(result?.properties.$referrer).toBe('not a url');
    });

    it('returns null events unchanged', () => {
      const before_send = config.before_send;
      if (typeof before_send !== 'function') {
        throw new Error('before_send must be a function');
      }
      expect(before_send(null)).toBeNull();
    });
  });
});
