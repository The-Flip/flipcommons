import { describe, expect, it } from 'vitest';

import {
  creditsChanged,
  diffScalarFields,
  publicIdSetChanged,
  stringSetChanged,
} from './edit-helpers';

// Form fields use string | number (NumberField returns number, cleared fields are '')
type TestFields = Record<string, string | number>;

describe('diffScalarFields', () => {
  it('detects changed fields', () => {
    const current: TestFields = { name: 'Updated', year: 1998 };
    const original: TestFields = { name: 'Original', year: 1998 };
    expect(diffScalarFields(current, original)).toEqual({ name: 'Updated' });
  });

  it('maps empty string to null', () => {
    const current: TestFields = { name: '', year: '' };
    const original: TestFields = { name: 'Original', year: 1998 };
    expect(diffScalarFields(current, original)).toEqual({ name: null, year: null });
  });

  it('treats NaN as empty string', () => {
    const current: TestFields = { value: NaN };
    const original: TestFields = { value: 42 };
    expect(diffScalarFields(current, original)).toEqual({ value: null });
  });

  it('returns empty object when nothing changed', () => {
    const fields: TestFields = { name: 'Same', year: 1997 };
    expect(diffScalarFields(fields, fields)).toEqual({});
  });

  it('compares by string coercion', () => {
    // Number 1997 vs string "1997" — same after String()
    const current: TestFields = { year: 1997 };
    const original: TestFields = { year: '1997' };
    expect(diffScalarFields(current, original)).toEqual({});
  });

  it('treats NaN and empty string as no change', () => {
    const current: TestFields = { value: NaN };
    const original: TestFields = { value: '' };
    expect(diffScalarFields(current, original)).toEqual({});
  });
});

describe('publicIdSetChanged', () => {
  it('returns false when sets match', () => {
    expect(publicIdSetChanged(['a', 'b'], [{ public_id: 'b' }, { public_id: 'a' }])).toBe(false);
  });

  it('returns true when slug added', () => {
    expect(publicIdSetChanged(['a', 'b', 'c'], [{ public_id: 'a' }, { public_id: 'b' }])).toBe(
      true,
    );
  });

  it('returns true when slug removed', () => {
    expect(publicIdSetChanged(['a'], [{ public_id: 'a' }, { public_id: 'b' }])).toBe(true);
  });

  it('returns false for empty vs empty', () => {
    expect(publicIdSetChanged([], [])).toBe(false);
  });

  it('returns true for empty vs non-empty', () => {
    expect(publicIdSetChanged([], [{ public_id: 'a' }])).toBe(true);
  });
});

describe('stringSetChanged', () => {
  it('returns false when sets match', () => {
    expect(stringSetChanged(['b', 'a'], ['a', 'b'])).toBe(false);
  });

  it('returns true when string added', () => {
    expect(stringSetChanged(['a', 'b', 'c'], ['a', 'b'])).toBe(true);
  });

  it('returns true when string removed', () => {
    expect(stringSetChanged(['a'], ['a', 'b'])).toBe(true);
  });

  it('returns false for empty vs empty', () => {
    expect(stringSetChanged([], [])).toBe(false);
  });
});

describe('creditsChanged', () => {
  it('returns false when current matches original', () => {
    const current = [
      { person_slug: 'pat-lawlor', role: 'game-design' },
      { person_slug: 'john-youssi', role: 'artwork' },
    ];
    const original = [
      { person: { public_id: 'pat-lawlor' }, role: 'game-design' },
      { person: { public_id: 'john-youssi' }, role: 'artwork' },
    ];
    expect(creditsChanged(current, original)).toBe(false);
  });

  it('returns true when a credit is added', () => {
    const current = [
      { person_slug: 'pat-lawlor', role: 'game-design' },
      { person_slug: 'john-youssi', role: 'artwork' },
    ];
    const original = [{ person: { public_id: 'pat-lawlor' }, role: 'game-design' }];
    expect(creditsChanged(current, original)).toBe(true);
  });

  it('returns true when a credit is removed', () => {
    const current = [{ person_slug: 'pat-lawlor', role: 'game-design' }];
    const original = [
      { person: { public_id: 'pat-lawlor' }, role: 'game-design' },
      { person: { public_id: 'john-youssi' }, role: 'artwork' },
    ];
    expect(creditsChanged(current, original)).toBe(true);
  });

  it('returns true when a role is changed', () => {
    const current = [{ person_slug: 'pat-lawlor', role: 'mechanical-design' }];
    const original = [{ person: { public_id: 'pat-lawlor' }, role: 'game-design' }];
    expect(creditsChanged(current, original)).toBe(true);
  });

  it('filters out incomplete rows from current', () => {
    const current = [
      { person_slug: 'pat-lawlor', role: 'game-design' },
      { person_slug: '', role: 'artwork' },
      { person_slug: 'john-youssi', role: '' },
    ];
    const original = [{ person: { public_id: 'pat-lawlor' }, role: 'game-design' }];
    expect(creditsChanged(current, original)).toBe(false);
  });

  it('filters out rows with null person_slug or role', () => {
    // SearchableSelect sets value to null on deselect, not ''
    const current = [
      { person_slug: 'pat-lawlor', role: 'game-design' },
      { person_slug: 'john-youssi', role: null as unknown as string },
    ];
    const original = [{ person: { public_id: 'pat-lawlor' }, role: 'game-design' }];
    expect(creditsChanged(current, original)).toBe(false);
  });

  it('returns false for empty arrays on both sides', () => {
    expect(creditsChanged([], [])).toBe(false);
  });

  it('is order-independent', () => {
    const current = [
      { person_slug: 'john-youssi', role: 'artwork' },
      { person_slug: 'pat-lawlor', role: 'game-design' },
    ];
    const original = [
      { person: { public_id: 'pat-lawlor' }, role: 'game-design' },
      { person: { public_id: 'john-youssi' }, role: 'artwork' },
    ];
    expect(creditsChanged(current, original)).toBe(false);
  });
});
