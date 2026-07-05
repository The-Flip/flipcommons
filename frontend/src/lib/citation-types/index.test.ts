/**
 * Tests for the citation-type registry helpers — the type-driven lookups
 * shared code uses instead of naming a citation type.
 */
import { describe, expect, it } from 'vitest';
import { displayLocator } from './index';

describe('displayLocator', () => {
  it('prefixes a video timestamp so it reads as a start point', () => {
    expect(displayLocator('video', '1:02:03')).toBe('starting at 1:02:03');
  });

  it('leaves a freeform locator unchanged (no prefix)', () => {
    expect(displayLocator('book', 'p. 42')).toBe('p. 42');
  });

  it('returns empty for an empty locator, whatever the type', () => {
    expect(displayLocator('video', '')).toBe('');
    expect(displayLocator('book', '')).toBe('');
  });

  it('falls back to no prefix for an unknown type', () => {
    expect(displayLocator('podcast', '1:02:03')).toBe('1:02:03');
  });
});
