import { describe, it, expect } from 'vitest';
import { absoluteAssetUrl, formatYearRange, normalizeText, pluralize } from './utils';

describe('normalizeText', () => {
  it('lowercases text', () => {
    expect(normalizeText('Hello World')).toBe('hello world');
  });

  it('strips diacritics', () => {
    expect(normalizeText('café')).toBe('cafe');
    expect(normalizeText('naïve')).toBe('naive');
  });

  it('strips punctuation so colon-separated words match', () => {
    expect(normalizeText('Ultraman: Kaiju Rumble')).toBe('ultraman kaiju rumble');
  });

  it('strips hyphens', () => {
    expect(normalizeText('Spider-Man')).toBe('spiderman');
  });

  it('strips apostrophes', () => {
    expect(normalizeText("Ripley's Believe It or Not")).toBe('ripleys believe it or not');
  });

  it('collapses multiple spaces', () => {
    expect(normalizeText('foo   bar')).toBe('foo bar');
  });

  it('trims leading and trailing whitespace', () => {
    expect(normalizeText('  hello  ')).toBe('hello');
  });

  it('handles empty string', () => {
    expect(normalizeText('')).toBe('');
  });
});

describe('formatYearRange', () => {
  it('returns range when both years present', () => {
    expect(formatYearRange(1927, 1983)).toBe('1927\u20131983');
  });

  it('returns open-ended range when only start', () => {
    expect(formatYearRange(1999, null)).toBe('1999\u2013present');
  });

  it('returns leading dash when only end', () => {
    expect(formatYearRange(null, 1950)).toBe('\u20131950');
  });

  it('returns null when neither year present', () => {
    expect(formatYearRange(null, null)).toBeNull();
    expect(formatYearRange(undefined, undefined)).toBeNull();
  });
});

describe('pluralize', () => {
  it('uses singular form for 1', () => {
    expect(pluralize(1, 'model')).toBe('1 model');
  });

  it('appends s for n != 1', () => {
    expect(pluralize(0, 'model')).toBe('0 models');
    expect(pluralize(2, 'model')).toBe('2 models');
  });

  it('uses explicit plural form when provided', () => {
    expect(pluralize(2, 'child', 'children')).toBe('2 children');
    expect(pluralize(1, 'child', 'children')).toBe('1 child');
  });
});

describe('absoluteAssetUrl', () => {
  // In the test environment, `paths.assets` isn't configured, so `asset()`
  // returns the path unchanged — exercising the relative-path-resolved-
  // against-origin branch.
  const pageUrl = new URL('https://flipcommons.org/about/people');

  it('resolves a relative asset path against the page origin', () => {
    expect(absoluteAssetUrl('/images/social_default.png', pageUrl)).toBe(
      'https://flipcommons.org/images/social_default.png',
    );
  });

  it('produces an absolute URL regardless of the current page path', () => {
    const deep = new URL('https://flipcommons.org/some/deep/route?x=1#y');
    expect(absoluteAssetUrl('/img.png', deep)).toBe('https://flipcommons.org/img.png');
  });
});
