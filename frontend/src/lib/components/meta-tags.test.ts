import { describe, expect, test } from 'vitest';
import {
  buildFullTitle,
  truncateMetaDescription,
  truncateOgDescription,
  buildCanonicalUrl,
  twitterCardType,
} from './meta-tags';
import { SITE_TITLE } from '$lib/constants';

describe('buildFullTitle', () => {
  test('appends site title suffix', () => {
    expect(buildFullTitle('Medieval Madness')).toBe(`Medieval Madness — ${SITE_TITLE}`);
  });

  test('does not double site title', () => {
    expect(buildFullTitle(SITE_TITLE)).toBe(SITE_TITLE);
  });
});

describe('truncateMetaDescription', () => {
  test('short description passes through unchanged', () => {
    expect(truncateMetaDescription('A short description.')).toBe('A short description.');
  });

  test('exactly 155 chars passes through unchanged', () => {
    const desc = 'x'.repeat(155);
    expect(truncateMetaDescription(desc)).toBe(desc);
  });

  test('truncates at 154 chars with ellipsis', () => {
    const desc = 'x'.repeat(200);
    const result = truncateMetaDescription(desc);
    expect(result).toHaveLength(155);
    expect(result).toBe('x'.repeat(154) + '\u2026');
  });
});

describe('truncateOgDescription', () => {
  test('short description passes through unchanged', () => {
    expect(truncateOgDescription('A short description.')).toBe('A short description.');
  });

  test('exactly 200 chars passes through unchanged', () => {
    const desc = 'x'.repeat(200);
    expect(truncateOgDescription(desc)).toBe(desc);
  });

  test('truncates at 199 chars with ellipsis', () => {
    const desc = 'x'.repeat(250);
    const result = truncateOgDescription(desc);
    expect(result).toHaveLength(200);
    expect(result).toBe('x'.repeat(199) + '\u2026');
  });
});

describe('buildCanonicalUrl', () => {
  test('strips query params', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo?ref=twitter')).toBe(
      'https://example.com/models/foo',
    );
  });

  test('strips hash', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo#section')).toBe(
      'https://example.com/models/foo',
    );
  });

  test('strips both query and hash', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo?a=1#top')).toBe(
      'https://example.com/models/foo',
    );
  });

  test('clean URL passes through unchanged', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo')).toBe(
      'https://example.com/models/foo',
    );
  });
});

describe('twitterCardType', () => {
  test('returns summary_large_image when image is present', () => {
    expect(twitterCardType('https://example.com/img.jpg')).toBe('summary_large_image');
  });

  test('returns summary when image is null', () => {
    expect(twitterCardType(null)).toBe('summary');
  });

  test('returns summary when image is undefined', () => {
    expect(twitterCardType(undefined)).toBe('summary');
  });

  test('returns summary when image is empty string', () => {
    expect(twitterCardType('')).toBe('summary');
  });
});
