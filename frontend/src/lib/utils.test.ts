import { describe, it, expect } from 'vitest';
import { absoluteAssetUrl, formatActiveRange, normalizeText, pluralize } from './utils';

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

describe('formatActiveRange', () => {
  const thisYear = new Date().getFullYear();
  const recent = thisYear - 2; // within the 6-year recency window
  const old = thisYear - 20; // well outside it

  it('renders ongoing makers as open-ended, regardless of last model age', () => {
    expect(formatActiveRange(1971, old, 'ongoing')).toBe(`1971–present`);
  });

  it('renders ended makers as a closed range', () => {
    expect(formatActiveRange(1931, 1998, 'ended')).toBe('1931–1998');
  });

  it('collapses a single-year closed range to one year', () => {
    expect(formatActiveRange(1985, 1985, 'ended')).toBe('1985');
    expect(formatActiveRange(old, old, 'unknown')).toBe(`${old}`);
  });

  it('treats a recent unknown maker as still producing', () => {
    expect(formatActiveRange(1990, recent, 'unknown')).toBe(`1990–present`);
  });

  it('closes an unknown maker whose last model is older than the window', () => {
    expect(formatActiveRange(1990, old, 'unknown')).toBe(`1990–${old}`);
  });

  it('returns null when the span has no anchoring year', () => {
    expect(formatActiveRange(null, null, 'ended')).toBeNull();
    expect(formatActiveRange(1990, null, 'ongoing')).toBeNull();
    expect(formatActiveRange(undefined, undefined, 'unknown')).toBeNull();
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
