import { describe, expect, it } from 'vitest';
import type { FieldChangeSchema } from '$lib/api/schema';
import {
  formatValue,
  hasMeaningfulValue,
  isDeletion,
  isDiffable,
  isUnchanged,
  simplifyClaimValue,
} from './change-display';

/** Build a minimal FieldChangeSchema with raw-only old/new values. */
function fc(
  oldRaw: unknown,
  newRaw: unknown,
  field_name = 'field',
  claim_key = 'k',
): FieldChangeSchema {
  return {
    field_name,
    claim_key,
    old_value: oldRaw === undefined ? null : { raw: oldRaw },
    new_value: { raw: newRaw },
  };
}

describe('formatValue', () => {
  it('returns em-dash for null', () => {
    expect(formatValue(null)).toBe('—');
  });

  it('returns em-dash for undefined', () => {
    expect(formatValue(undefined)).toBe('—');
  });

  it('returns em-dash for empty string', () => {
    expect(formatValue('')).toBe('—');
  });

  it('returns short strings verbatim', () => {
    expect(formatValue('hello')).toBe('hello');
  });

  it('preserves long strings verbatim (callers control overflow via CSS)', () => {
    const long = 'a'.repeat(150);
    expect(formatValue(long)).toBe(long);
  });

  it('JSON-serializes non-string values', () => {
    expect(formatValue(42)).toBe('42');
    expect(formatValue(true)).toBe('true');
    expect(formatValue({ key: 'val' })).toBe('{"key":"val"}');
  });

  it('preserves long JSON-serialized values verbatim', () => {
    const obj = { data: 'x'.repeat(200) };
    expect(formatValue(obj)).toBe(JSON.stringify(obj));
  });
});

describe('isDiffable', () => {
  it('returns true when old_value.raw is a long string', () => {
    expect(isDiffable(fc('a'.repeat(81), 'short'))).toBe(true);
  });

  it('returns true when new_value.raw is a long string', () => {
    expect(isDiffable(fc('short', 'b'.repeat(81)))).toBe(true);
  });

  it('returns false when both strings are short', () => {
    expect(isDiffable(fc('short old', 'short new'))).toBe(false);
  });

  it('returns false when old_value is null', () => {
    const change: FieldChangeSchema = {
      field_name: 'name',
      claim_key: 'k',
      old_value: null,
      new_value: { raw: 'a'.repeat(100) },
    };
    expect(isDiffable(change)).toBe(false);
  });

  it('returns false when new_value.raw is a number', () => {
    expect(isDiffable(fc('a'.repeat(100), 1990))).toBe(false);
  });

  it('returns false at exactly the 80-character boundary', () => {
    expect(isDiffable(fc('a'.repeat(80), 'b'.repeat(80)))).toBe(false);
  });

  it('returns true when one string is exactly 81 characters', () => {
    expect(isDiffable(fc('a'.repeat(81), 'short'))).toBe(true);
  });
});

describe('isUnchanged', () => {
  it('is true when scalar values are equal', () => {
    expect(isUnchanged(fc('solid-state', 'solid-state'))).toBe(true);
  });

  it('is false when scalar values differ', () => {
    expect(isUnchanged(fc('electromechanical', 'solid-state'))).toBe(false);
  });

  it('is false when only one side is null', () => {
    const change: FieldChangeSchema = {
      field_name: 'tech',
      claim_key: 'k',
      old_value: null,
      new_value: { raw: 'solid-state' },
    };
    expect(isUnchanged(change)).toBe(false);
  });

  it('is true when both sides are null (nothing asserted)', () => {
    const change: FieldChangeSchema = {
      field_name: 'tech',
      claim_key: 'k',
      old_value: null,
      new_value: { raw: null },
    };
    expect(isUnchanged(change)).toBe(true);
  });

  it('is true when arrays have the same contents', () => {
    expect(isUnchanged(fc(['a', 'b'], ['a', 'b']))).toBe(true);
  });
});

describe('hasMeaningfulValue', () => {
  it('rejects null, undefined, and empty string', () => {
    expect(hasMeaningfulValue(null)).toBe(false);
    expect(hasMeaningfulValue(undefined)).toBe(false);
    expect(hasMeaningfulValue('')).toBe(false);
  });

  it('rejects a bare retraction marker {exists: false}', () => {
    expect(hasMeaningfulValue({ exists: false })).toBe(false);
  });

  it('accepts a positive relationship claim {value, exists: true}', () => {
    expect(hasMeaningfulValue({ value: 'DW', exists: true })).toBe(true);
  });

  it('accepts a negative relationship claim with payload {value, exists: false}', () => {
    expect(hasMeaningfulValue({ value: 'DW', exists: false })).toBe(true);
  });

  it('accepts ordinary scalars', () => {
    expect(hasMeaningfulValue('solid-state')).toBe(true);
    expect(hasMeaningfulValue(0)).toBe(true);
    expect(hasMeaningfulValue(false)).toBe(true);
  });
});

describe('isDeletion', () => {
  it('is true when old has a value and new is null', () => {
    expect(isDeletion(fc('Save the universe', null))).toBe(true);
  });

  it('is true when old has a value and new is empty string', () => {
    expect(isDeletion(fc('Save the universe', ''))).toBe(true);
  });

  it('is false for a normal edit (both sides have a value)', () => {
    expect(isDeletion(fc('foo', 'bar'))).toBe(false);
  });

  it('is false for a creation (old_value bundle is null)', () => {
    const change: FieldChangeSchema = {
      field_name: 'tagline',
      claim_key: 'k',
      old_value: null,
      new_value: { raw: 'bar' },
    };
    expect(isDeletion(change)).toBe(false);
  });

  it('is false when both sides are empty (no real change to display)', () => {
    const change: FieldChangeSchema = {
      field_name: 'tagline',
      claim_key: 'k',
      old_value: null,
      new_value: { raw: null },
    };
    expect(isDeletion(change)).toBe(false);
  });

  it('is false when old is a bare retraction marker (no prior assertion)', () => {
    // After delete-then-re-set, the backend supplies the prior retraction
    // marker as old_value.raw. That is not a real prior value, so this is
    // a creation, not an edit.
    expect(isDeletion(fc({ exists: false }, 'plasma-dmd'))).toBe(false);
  });
});

describe('simplifyClaimValue', () => {
  it('extracts a positive abbreviation claim', () => {
    expect(simplifyClaimValue({ value: 'DW', exists: true })).toEqual({
      display: 'DW',
      exists: true,
    });
  });

  it('extracts a negative abbreviation claim', () => {
    expect(simplifyClaimValue({ value: 'DW', exists: false })).toEqual({
      display: 'DW',
      exists: false,
    });
  });

  it('extracts an alias-style single-key claim regardless of key name', () => {
    expect(simplifyClaimValue({ alias_value: 'Doctor Who', exists: true })).toEqual({
      display: 'Doctor Who',
      exists: true,
    });
  });

  it('returns null for credit-style multi-key claims', () => {
    expect(simplifyClaimValue({ person: 1, role: 2, exists: true })).toBeNull();
  });

  it('returns null for FK-pk integer values (not human-readable)', () => {
    expect(simplifyClaimValue({ theme: 1, exists: true })).toBeNull();
  });

  it('returns null when exists is missing', () => {
    expect(simplifyClaimValue({ value: 'DW' })).toBeNull();
  });

  it('returns null for bare scalars', () => {
    expect(simplifyClaimValue('solid-state')).toBeNull();
    expect(simplifyClaimValue(42)).toBeNull();
    expect(simplifyClaimValue(null)).toBeNull();
  });

  it('returns null for arrays', () => {
    expect(simplifyClaimValue(['a', 'b'])).toBeNull();
  });

  it('returns null for retraction-only dicts (just exists:false)', () => {
    expect(simplifyClaimValue({ exists: false })).toBeNull();
  });
});
