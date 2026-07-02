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
  locator: 'p. 2',
};

describe('buildEditCitationsRequest', () => {
  it('serializes the selected citation as a content spec', () => {
    expect(buildEditCitationsRequest(citation)).toEqual([
      { citation_source_id: 7, locator: 'p. 2' },
    ]);
  });

  it('sends an empty list when none is selected', () => {
    expect(buildEditCitationsRequest(null)).toEqual([]);
  });
});

describe('withEditMetadata', () => {
  it('adds trimmed note and citations to an existing patch body', () => {
    expect(
      withEditMetadata({ fields: { description: 'Updated' } }, '  cleanup  ', citation),
    ).toEqual({
      fields: { description: 'Updated' },
      note: 'cleanup',
      citations: [{ citation_source_id: 7, locator: 'p. 2' }],
    });
  });

  it('sends empty citations for bodies without a citation', () => {
    expect(withEditMetadata({ fields: { description: 'Updated' } }, '', null)).toEqual({
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
        citations: [{ citation_source_id: 7, locator: 'p. 2' }],
      }),
    ).toBe(3);
  });

  it('returns zero for empty bodies', () => {
    expect(countPendingChanges(null)).toBe(0);
  });
});

describe('shouldShowMixedEditCitationWarning', () => {
  it('warns when one citation is attached to multiple pending changes', () => {
    expect(
      shouldShowMixedEditCitationWarning(
        {
          fields: { year: 1998, description: 'Updated' },
        },
        citation,
      ),
    ).toBe(true);
  });

  it('does not warn for a single pending change or no citation', () => {
    expect(
      shouldShowMixedEditCitationWarning(
        {
          fields: { description: 'Updated' },
        },
        citation,
      ),
    ).toBe(false);
    expect(
      shouldShowMixedEditCitationWarning(
        {
          fields: { description: 'Updated', year: 1998 },
        },
        null,
      ),
    ).toBe(false);
  });
});
