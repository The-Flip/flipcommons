import { describe, expect, it } from 'vitest';

import {
  buildEditCitationsRequest,
  countPendingChanges,
  shouldShowMixedEditCitationWarning,
  withEditMetadata,
  type EditCitationSelection,
} from './edit-citation';

const citation: EditCitationSelection = {
  citationSourceId: 7,
  sourceName: 'Williams Flyer',
  sourceType: 'web',
  locator: 'p. 2',
  quote: 'Released in 1997.',
};

const secondCitation: EditCitationSelection = {
  citationSourceId: 9,
  sourceName: 'Internet Pinball Database #4032',
  sourceType: 'database',
  locator: '',
  quote: '',
};

describe('buildEditCitationsRequest', () => {
  it('serializes every selected citation as a content spec, in order', () => {
    expect(buildEditCitationsRequest([citation, secondCitation])).toEqual([
      { citation_source_id: 7, locator: 'p. 2', quote: 'Released in 1997.' },
      { citation_source_id: 9, locator: '', quote: '' },
    ]);
  });

  it('sends an empty list when none is selected', () => {
    expect(buildEditCitationsRequest([])).toEqual([]);
  });
});

describe('withEditMetadata', () => {
  it('adds trimmed note and citations to an existing patch body', () => {
    expect(
      withEditMetadata({ fields: { description: 'Updated' } }, '  cleanup  ', [citation]),
    ).toEqual({
      fields: { description: 'Updated' },
      note: 'cleanup',
      citations: [{ citation_source_id: 7, locator: 'p. 2', quote: 'Released in 1997.' }],
    });
  });

  it('sends empty citations for bodies without a citation', () => {
    expect(withEditMetadata({ fields: { description: 'Updated' } }, '', [])).toEqual({
      fields: { description: 'Updated' },
      note: '',
      citations: [],
    });
  });
});

describe('countPendingChanges', () => {
  it('counts scalar field changes individually and relationship buckets once', () => {
    expect(
      countPendingChanges({
        fields: { year: 1998, description: 'Updated' },
        themes: ['medieval'],
        note: 'ignored',
        citations: [{ citation_source_id: 7, locator: 'p. 2', quote: 'Released in 1997.' }],
      }),
    ).toBe(3);
  });

  it('returns zero for empty bodies', () => {
    expect(countPendingChanges(null)).toBe(0);
  });
});

describe('shouldShowMixedEditCitationWarning', () => {
  it('warns when citations are attached to multiple pending changes', () => {
    expect(
      shouldShowMixedEditCitationWarning(
        {
          fields: { year: 1998, description: 'Updated' },
        },
        [citation, secondCitation],
      ),
    ).toBe(true);
  });

  it('does not warn for a single pending change or no citations', () => {
    expect(
      shouldShowMixedEditCitationWarning(
        {
          fields: { description: 'Updated' },
        },
        [citation],
      ),
    ).toBe(false);
    expect(
      shouldShowMixedEditCitationWarning(
        {
          fields: { description: 'Updated', year: 1998 },
        },
        [],
      ),
    ).toBe(false);
  });
});
