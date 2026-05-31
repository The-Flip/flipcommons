import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ClaimDisplayValueSchema } from '$lib/api/schema';
import {
  buildDisplaySegments,
  DELETED_PLACEHOLDER,
  IDENTITY_SEPARATOR,
  MISSING_PLACEHOLDER,
} from './claim-display';
import { _resetQualifierWarnings } from './qualifier-renderers';

function display(partial: Partial<ClaimDisplayValueSchema>): ClaimDisplayValueSchema {
  return { identity: [], qualifiers: [], ...partial };
}

describe('buildDisplaySegments', () => {
  it('renders a single resolved identity as one text segment', () => {
    const out = buildDisplaySegments(
      display({ identity: [{ key: 'theme', label: 'Horror', state: 'resolved' }] }),
    );
    expect(out).toEqual([{ text: 'Horror', missing: false }]);
  });

  it('joins two resolved identities with the em-dash separator', () => {
    const out = buildDisplaySegments(
      display({
        identity: [
          { key: 'person', label: 'Pat Lawlor', state: 'resolved' },
          { key: 'role', label: 'Art', state: 'resolved' },
        ],
      }),
    );
    expect(out).toEqual([
      { text: 'Pat Lawlor', missing: false },
      { text: IDENTITY_SEPARATOR, missing: false },
      { text: 'Art', missing: false },
    ]);
  });

  it('marks deleted identities for placeholder styling', () => {
    const out = buildDisplaySegments(
      display({ identity: [{ key: 'person', label: null, state: 'deleted' }] }),
    );
    expect(out).toEqual([{ text: DELETED_PLACEHOLDER, missing: true }]);
  });

  it('marks missing identities for placeholder styling', () => {
    const out = buildDisplaySegments(
      display({ identity: [{ key: 'person', label: null, state: 'missing' }] }),
    );
    expect(out).toEqual([{ text: MISSING_PLACEHOLDER, missing: true }]);
  });

  it('treats a resolved-but-null label as empty text rather than placeholder', () => {
    // Empty-string identity (e.g. a deliberately blank abbreviation) renders
    // as "" with normal styling. Backend signals this as state="resolved"
    // with label="" or null; either way the renderer treats it as data.
    const out = buildDisplaySegments(
      display({ identity: [{ key: 'value', label: null, state: 'resolved' }] }),
    );
    expect(out).toEqual([{ text: '', missing: false }]);
  });

  it('appends qualifier fragments after the identity', () => {
    const out = buildDisplaySegments(
      display({
        identity: [{ key: 'gameplay_feature', label: 'Multiball', state: 'resolved' }],
        qualifiers: [{ key: 'count', value: 3 }],
      }),
    );
    expect(out).toEqual([
      { text: 'Multiball', missing: false },
      { text: ' ×3', missing: false },
    ]);
  });

  it('omits the qualifier segment when all qualifiers render to empty', () => {
    // count=1 → '' per the qualifier renderer rules.
    const out = buildDisplaySegments(
      display({
        identity: [{ key: 'gameplay_feature', label: 'Multiball', state: 'resolved' }],
        qualifiers: [{ key: 'count', value: 1 }],
      }),
    );
    expect(out).toEqual([{ text: 'Multiball', missing: false }]);
  });

  describe('unknown qualifier keys', () => {
    beforeEach(() => {
      _resetQualifierWarnings();
      vi.spyOn(console, 'warn').mockImplementation(() => {});
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('falls through to default rendering for unknown keys', () => {
      const out = buildDisplaySegments(
        display({
          identity: [{ key: 'thing', label: 'Widget', state: 'resolved' }],
          qualifiers: [{ key: 'weirdkey', value: 'hello' }],
        }),
      );
      expect(out).toEqual([
        { text: 'Widget', missing: false },
        { text: ' (weirdkey: hello)', missing: false },
      ]);
    });
  });
});
