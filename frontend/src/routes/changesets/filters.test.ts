import { describe, expect, it } from 'vitest';
import { afterFor, changesFilterCodec, toEntityTypeFilter, toTimeRangeFilter } from './filters';

describe('changesFilterCodec.parse', () => {
  it('reads both dimensions from the query string', () => {
    expect(changesFilterCodec.parse(new URLSearchParams('entity_type=model&range=7d'))).toEqual({
      entity_type: 'model',
      range: '7d',
    });
  });

  it('defaults to no filters when the query string is empty', () => {
    expect(changesFilterCodec.parse(new URLSearchParams(''))).toEqual({
      entity_type: '',
      range: '',
    });
  });

  it('drops an unknown entity type rather than passing it through', () => {
    expect(changesFilterCodec.parse(new URLSearchParams('entity_type=widget')).entity_type).toBe(
      '',
    );
  });

  it('drops an unknown time range rather than passing it through', () => {
    expect(changesFilterCodec.parse(new URLSearchParams('range=1y')).range).toBe('');
  });

  it('ignores params outside the declaration', () => {
    expect(changesFilterCodec.parse(new URLSearchParams('utm_source=x&entity_type=title'))).toEqual(
      { entity_type: 'title', range: '' },
    );
  });
});

describe('changesFilterCodec.canonical', () => {
  it('serializes an active filter set', () => {
    expect(changesFilterCodec.canonical({ entity_type: 'person', range: '24h' })).toBe(
      'entity_type=person&range=24h',
    );
  });

  it('serializes empty state to the empty string', () => {
    expect(changesFilterCodec.canonical({ entity_type: '', range: '' })).toBe('');
  });

  it('omits an absent dimension', () => {
    expect(changesFilterCodec.canonical({ entity_type: '', range: '30d' })).toBe('range=30d');
  });

  it('round-trips through parse', () => {
    const state = { entity_type: 'manufacturer', range: '7d' } as const;
    expect(
      changesFilterCodec.parse(new URLSearchParams(changesFilterCodec.canonical(state))),
    ).toEqual(state);
  });
});

describe('afterFor', () => {
  const now = new Date('2026-08-24T12:00:00.000Z');

  it('returns undefined for all time', () => {
    expect(afterFor('', now)).toBeUndefined();
  });

  it('resolves a lookback window to an ISO timestamp', () => {
    expect(afterFor('24h', now)).toBe('2026-08-23T12:00:00.000Z');
    expect(afterFor('7d', now)).toBe('2026-08-17T12:00:00.000Z');
    expect(afterFor('30d', now)).toBe('2026-07-25T12:00:00.000Z');
  });
});

describe('option coercion', () => {
  it('accepts known values', () => {
    expect(toEntityTypeFilter('title')).toBe('title');
    expect(toTimeRangeFilter('30d')).toBe('30d');
  });

  it('folds null and unknown values to absent', () => {
    expect(toEntityTypeFilter(null)).toBe('');
    expect(toEntityTypeFilter('nope')).toBe('');
    expect(toTimeRangeFilter(null)).toBe('');
    expect(toTimeRangeFilter('nope')).toBe('');
  });
});
