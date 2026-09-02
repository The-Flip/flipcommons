import { describe, expect, it } from 'vitest';

import { matchDetailSubroute } from './detail-subroute-match';

describe('matchDetailSubroute', () => {
  it('returns the sub-route segment', () => {
    expect(matchDetailSubroute('/titles/[slug]/edit-history')).toBe('edit-history');
    expect(matchDetailSubroute('/titles/[slug]/sources')).toBe('sources');
    expect(matchDetailSubroute('/manufacturers/[slug]/edit')).toBe('edit');
  });

  it('returns the first sub-route segment for nested sub-routes', () => {
    expect(matchDetailSubroute('/models/[slug]/edit/[section]')).toBe('edit');
    expect(matchDetailSubroute('/titles/[slug]/models/new')).toBe('models');
  });

  it('reads a multi-segment public id as one segment', () => {
    // A Location's public_id spans several URL segments (`canada/on`) but a
    // single route segment, so its sub-routes sit where every other entity's do.
    expect(matchDetailSubroute('/locations/[...path]/edit-history')).toBe('edit-history');
    expect(matchDetailSubroute('/locations/[...path]/sources')).toBe('sources');
    expect(matchDetailSubroute('/locations/[...path]/edit/[section]')).toBe('edit');
  });

  it('returns null for routes with fewer than three segments', () => {
    expect(matchDetailSubroute('/titles')).toBeNull();
    expect(matchDetailSubroute('/')).toBeNull();
  });

  it('returns null for a detail route', () => {
    // Including one reached by a record whose slug is `sources` — it is served
    // by /titles/[slug], which carries no sub-route segment at all.
    expect(matchDetailSubroute('/titles/[slug]')).toBeNull();
    expect(matchDetailSubroute('/locations/[...path]')).toBeNull();
  });

  it('returns null when the second segment is not a public-id slot', () => {
    expect(matchDetailSubroute('/kiosk/edit/[id]')).toBeNull();
  });

  it('returns null for an unmatched URL', () => {
    expect(matchDetailSubroute(null)).toBeNull();
  });
});
