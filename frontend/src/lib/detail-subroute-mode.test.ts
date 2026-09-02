import { describe, expect, it } from 'vitest';

import { resolveDetailSubrouteMode } from './detail-subroute-mode';

describe('resolveDetailSubrouteMode', () => {
  it('returns detail for the base reader route', () => {
    expect(resolveDetailSubrouteMode('/manufacturers/[slug]')).toBe('detail');
  });

  it('returns edit for the edit route', () => {
    expect(resolveDetailSubrouteMode('/manufacturers/[slug]/edit')).toBe('edit');
  });

  it('returns edit for nested edit routes', () => {
    expect(resolveDetailSubrouteMode('/models/[slug]/edit/[section]')).toBe('edit');
  });

  it('returns sources for the sources route', () => {
    expect(resolveDetailSubrouteMode('/titles/[slug]/sources')).toBe('sources');
  });

  it('returns edit-history for the edit history route', () => {
    expect(resolveDetailSubrouteMode('/titles/[slug]/edit-history')).toBe('edit-history');
  });

  it('resolves sub-routes of a multi-segment public id', () => {
    expect(resolveDetailSubrouteMode('/locations/[...path]/sources')).toBe('sources');
    expect(resolveDetailSubrouteMode('/locations/[...path]/edit-history')).toBe('edit-history');
    expect(resolveDetailSubrouteMode('/locations/[...path]/edit/[section]')).toBe('edit');
  });

  it('returns detail when a record slug happens to name a sub-route', () => {
    // /titles/sources is the detail page for a title with slug='sources'. It
    // is served by /titles/[slug], so no sub-route can be read out of it.
    expect(resolveDetailSubrouteMode('/titles/[slug]')).toBe('detail');
  });

  it('returns detail for a nested listing', () => {
    expect(resolveDetailSubrouteMode('/manufacturers/[slug]/systems')).toBe('detail');
  });

  it('returns detail for an unmatched URL', () => {
    expect(resolveDetailSubrouteMode(null)).toBe('detail');
  });
});
