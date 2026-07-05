/**
 * Tests for the video timestamp grammar mirror.
 *
 * The cases mirror the backend's authoritative suite
 * (`backend/apps/citation/tests/test_video_locators.py`) — if a form is
 * accepted or rejected differently on the two sides, the inline UX would
 * disagree with the write path.
 */
import { describe, expect, it } from 'vitest';
import { MAX_START_TIME_SECONDS, formatStartTime, parseStartTime, videoType } from './video';
import { citationTypeFrontend, citationTypeMeta } from './index';

describe('parseStartTime', () => {
  it.each([
    ['0', 0],
    ['95', 95],
    ['0:57', 57],
    ['1:35', 95],
    ['12:05', 725],
    ['90:00', 5400],
    ['1:02:03', 3723],
    ['1:2:3', 3723],
    ['1h2m3s', 3723],
    ['95s', 95],
    ['2m', 120],
    ['1H2M3S', 3723],
    [' 1:35 ', 95],
  ] as const)('accepts %s → %d', (raw, seconds) => {
    expect(parseStartTime(raw)).toBe(seconds);
  });

  it.each([
    '',
    '   ',
    'p. 42',
    '1:75',
    '1:75:00',
    '1:02:03:04',
    ':35',
    '1:',
    '-95',
    '1.5',
    '1m2h',
    '2x',
    'h',
    '1h 2m',
    '1:35s',
  ])('rejects %s', (raw) => {
    expect(parseStartTime(raw)).toBeNull();
  });

  it('caps at 100 hours', () => {
    expect(parseStartTime(String(MAX_START_TIME_SECONDS))).toBe(MAX_START_TIME_SECONDS);
    expect(parseStartTime(String(MAX_START_TIME_SECONDS + 1))).toBeNull();
  });
});

describe('formatStartTime', () => {
  it.each([
    [0, '0:00'],
    [57, '0:57'],
    [95, '1:35'],
    [725, '12:05'],
    [3599, '59:59'],
    [3600, '1:00:00'],
    [3723, '1:02:03'],
    [36000, '10:00:00'],
  ] as const)('formats %d → %s', (seconds, canonical) => {
    expect(formatStartTime(seconds)).toBe(canonical);
  });
});

describe('videoType.normalizeLocator', () => {
  it('canonicalizes accepted forms', () => {
    expect(videoType.normalizeLocator('1h2m3s')).toBe('1:02:03');
    expect(videoType.normalizeLocator('95')).toBe('1:35');
  });

  it('rejects junk', () => {
    expect(videoType.normalizeLocator('p. 42')).toBeNull();
  });

  it('canonical forms are fixed points', () => {
    for (const canonical of ['0:00', '0:57', '1:35', '12:05', '1:02:03', '10:00:00']) {
      expect(videoType.normalizeLocator(canonical)).toBe(canonical);
    }
  });
});

describe('registry lookup', () => {
  it('video resolves to the timestamp behavior and meta', () => {
    expect(citationTypeFrontend('video').normalizeLocator('95')).toBe('1:35');
    expect(citationTypeMeta('video').locatorKind).toBe('timestamp');
    expect(citationTypeMeta('video').locatorInvalidMessage).not.toBe('');
  });

  it('freeform types pass locators through', () => {
    for (const key of ['book', 'magazine', 'web']) {
      expect(citationTypeFrontend(key).normalizeLocator('p. 42')).toBe('p. 42');
    }
  });

  it('an unknown source_type degrades to freeform', () => {
    expect(citationTypeFrontend('').normalizeLocator('anything')).toBe('anything');
    expect(citationTypeMeta('').locatorKind).toBe('freeform');
  });
});
