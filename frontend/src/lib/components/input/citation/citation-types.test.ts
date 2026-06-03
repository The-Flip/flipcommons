import { describe, it, expect } from 'vitest';
import {
  suppressChildResults,
  isDraftSubmittable,
  emptyDraft,
  transition,
  parentContextFromSource,
  type CitationSourceResult,
  type CiteState,
  type CitationInstanceDraft,
  type ParentContext,
  type ExtractionDraft,
} from './citation-types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSource(overrides: Partial<CitationSourceResult> = {}): CitationSourceResult {
  return {
    id: 1,
    name: 'Test Source',
    source_type: 'book',
    author: '',
    publisher: '',
    parent_id: null,
    has_children: false,
    is_abstract: false,
    skip_locator: false,
    identifier_key: '',
    ...overrides,
  };
}

function makeParent(overrides: Partial<ParentContext> = {}): ParentContext {
  return {
    id: 1,
    name: 'Parent',
    source_type: 'book',
    author: '',
    identifier_key: '',
    ...overrides,
  };
}

function searchState(draftOverrides: Partial<CitationInstanceDraft> = {}): CiteState {
  return { stage: 'search', draft: { ...emptyDraft(), ...draftOverrides } };
}

function identifyState(
  parent: ParentContext = makeParent(),
  draftOverrides: Partial<CitationInstanceDraft> = {},
): CiteState {
  return { stage: 'identify', draft: { ...emptyDraft(), ...draftOverrides }, parent };
}

// ---------------------------------------------------------------------------
// suppressChildResults
// ---------------------------------------------------------------------------

describe('suppressChildResults', () => {
  it('filters out children whose parent is in the result set', () => {
    const parent = makeSource({ id: 10, has_children: true });
    const child = makeSource({ id: 11, parent_id: 10 });
    const result = suppressChildResults([parent, child]);
    expect(result).toEqual([parent]);
  });

  it('keeps children whose parent is NOT in the result set', () => {
    const child = makeSource({ id: 11, parent_id: 99 });
    const result = suppressChildResults([child]);
    expect(result).toEqual([child]);
  });

  it('returns all items when there are no parents', () => {
    const a = makeSource({ id: 1 });
    const b = makeSource({ id: 2 });
    const result = suppressChildResults([a, b]);
    expect(result).toEqual([a, b]);
  });

  it('returns empty array for empty input', () => {
    expect(suppressChildResults([])).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// parentContextFromSource
// ---------------------------------------------------------------------------

describe('parentContextFromSource', () => {
  it('extracts parent context from source result', () => {
    const source = makeSource({
      id: 10,
      name: 'IPDB',
      source_type: 'web',
      author: '',
      identifier_key: 'ipdb',
    });
    expect(parentContextFromSource(source)).toEqual({
      id: 10,
      name: 'IPDB',
      source_type: 'web',
      author: '',
      identifier_key: 'ipdb',
    });
  });
});

// ---------------------------------------------------------------------------
// isDraftSubmittable
// ---------------------------------------------------------------------------

describe('isDraftSubmittable', () => {
  it('returns true when sourceId is set and locator is non-empty', () => {
    expect(
      isDraftSubmittable({ sourceId: 1, sourceName: 'X', locator: 'p.5', skipLocator: false }),
    ).toBe(true);
  });

  it('returns true when sourceId is set and skipLocator is true', () => {
    expect(
      isDraftSubmittable({ sourceId: 1, sourceName: 'X', locator: '', skipLocator: true }),
    ).toBe(true);
  });

  it('returns false when sourceId is null', () => {
    expect(
      isDraftSubmittable({ sourceId: null, sourceName: '', locator: 'p.5', skipLocator: false }),
    ).toBe(false);
  });

  it('returns false when sourceId is set but locator empty and skipLocator false', () => {
    expect(
      isDraftSubmittable({ sourceId: 1, sourceName: 'X', locator: '', skipLocator: false }),
    ).toBe(false);
  });

  it('returns true when both locator and skipLocator are set', () => {
    expect(
      isDraftSubmittable({ sourceId: 1, sourceName: 'X', locator: 'p.5', skipLocator: true }),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// emptyDraft
// ---------------------------------------------------------------------------

describe('emptyDraft', () => {
  it('returns a fresh empty draft', () => {
    expect(emptyDraft()).toEqual({
      sourceId: null,
      sourceName: '',
      locator: '',
      skipLocator: false,
    });
  });

  it('returns a new object each time', () => {
    expect(emptyDraft()).not.toBe(emptyDraft());
  });
});

// ---------------------------------------------------------------------------
// transition (state machine)
// ---------------------------------------------------------------------------

describe('transition', () => {
  describe('source_selected', () => {
    it('abstract source → identify stage with parentContext', () => {
      const source = makeSource({
        id: 10,
        name: 'Book Series',
        source_type: 'book',
        author: 'Author A',
        is_abstract: true,
      });
      const state = searchState();
      const next = transition(state, { type: 'source_selected', source });

      expect(next.stage).toBe('identify');
      if (next.stage === 'identify') {
        expect(next.parent).toEqual({
          id: 10,
          name: 'Book Series',
          source_type: 'book',
          author: 'Author A',
          identifier_key: '',
        });
        expect(next.draft.sourceId).toBe(10);
        expect(next.draft.sourceName).toBe('Book Series');
      }
    });

    it('non-abstract source → locator stage with draft updated', () => {
      const source = makeSource({ id: 5, name: 'Concrete', skip_locator: false });
      const state = searchState();
      const next = transition(state, { type: 'source_selected', source });

      expect(next.stage).toBe('locator');
      expect(next.draft.sourceId).toBe(5);
      expect(next.draft.sourceName).toBe('Concrete');
      expect(next.draft.skipLocator).toBe(false);
    });

    it('non-abstract source with skip_locator → locator stage with skipLocator true', () => {
      const source = makeSource({ id: 6, name: 'Web Child', skip_locator: true });
      const state = searchState();
      const next = transition(state, { type: 'source_selected', source });

      expect(next.stage).toBe('locator');
      expect(next.draft.skipLocator).toBe(true);
    });
  });

  describe('source_identified', () => {
    it('from identify → locator stage with draft updated to child', () => {
      const state = identifyState(makeParent({ id: 10 }), { sourceId: 10, sourceName: 'Parent' });
      const next = transition(state, {
        type: 'source_identified',
        sourceId: 11,
        sourceName: 'Child Edition',
        skipLocator: false,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.sourceId).toBe(11);
      expect(next.draft.sourceName).toBe('Child Edition');
      expect(next.draft.skipLocator).toBe(false);
    });

    it('from identify with skipLocator true → locator stage with skipLocator set', () => {
      const state = identifyState();
      const next = transition(state, {
        type: 'source_identified',
        sourceId: 12,
        sourceName: 'IPDB Machine 4836',
        skipLocator: true,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.skipLocator).toBe(true);
    });

    it('from search → locator stage (recognition path)', () => {
      const state = searchState();
      const next = transition(state, {
        type: 'source_identified',
        sourceId: 21,
        sourceName: 'IPDB #4836',
        skipLocator: true,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.sourceId).toBe(21);
      expect(next.draft.sourceName).toBe('IPDB #4836');
      expect(next.draft.skipLocator).toBe(true);
    });
  });

  describe('source_create_started', () => {
    it('from search → create with parent: null', () => {
      const state = searchState();
      const next = transition(state, { type: 'source_create_started', prefillName: 'New Source' });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.parent).toBeNull();
        expect(next.prefillName).toBe('New Source');
      }
    });

    it('from identify → create with parent carried over', () => {
      const parent = makeParent({ id: 10, name: 'Book Series' });
      const state = identifyState(parent);
      const next = transition(state, { type: 'source_create_started', prefillName: 'New Edition' });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.parent).toEqual(parent);
        expect(next.prefillName).toBe('New Edition');
      }
    });
  });

  describe('source_created', () => {
    it('→ locator stage with draft updated to new source', () => {
      const state: CiteState = {
        stage: 'create',
        draft: emptyDraft(),
        parent: null,
        prefillName: 'New Source',
        extractionDraft: null,
      };
      const next = transition(state, {
        type: 'source_created',
        sourceId: 50,
        sourceName: 'New Source',
        skipLocator: false,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.sourceId).toBe(50);
      expect(next.draft.sourceName).toBe('New Source');
      expect(next.draft.skipLocator).toBe(false);
    });

    it('with skipLocator → locator stage with skipLocator true', () => {
      const state: CiteState = {
        stage: 'create',
        draft: emptyDraft(),
        parent: makeParent(),
        prefillName: 'Web Child',
        extractionDraft: null,
      };
      const next = transition(state, {
        type: 'source_created',
        sourceId: 51,
        sourceName: 'Web Child',
        skipLocator: true,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.skipLocator).toBe(true);
    });
  });

  describe('extraction_draft_ready', () => {
    const draft: ExtractionDraft = {
      name: 'Learning Python',
      source_type: 'book',
      author: 'Mark Lutz',
      publisher: "O'Reilly Media",
      year: 2009,
      isbn: '9780596517748',
    };

    it('from search → create with extractionDraft populated', () => {
      const state = searchState();
      const next = transition(state, { type: 'extraction_draft_ready', extractionDraft: draft });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.extractionDraft).toEqual(draft);
        expect(next.prefillName).toBe('Learning Python');
        expect(next.parent).toBeNull();
      }
    });

    it('from identify → no-op', () => {
      const state = identifyState();
      const next = transition(state, { type: 'extraction_draft_ready', extractionDraft: draft });
      expect(next).toBe(state);
    });

    it('from locator → no-op', () => {
      const state: CiteState = { stage: 'locator', draft: emptyDraft() };
      const next = transition(state, { type: 'extraction_draft_ready', extractionDraft: draft });
      expect(next).toBe(state);
    });
  });

  describe('source_create_started sets extractionDraft null', () => {
    it('from search → create with extractionDraft: null', () => {
      const state = searchState();
      const next = transition(state, { type: 'source_create_started', prefillName: 'Manual' });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.extractionDraft).toBeNull();
      }
    });
  });

  describe('invalid transitions', () => {
    const source = makeSource({ id: 1 });

    it('source_created from search → no-op', () => {
      const state = searchState();
      const next = transition(state, {
        type: 'source_created',
        sourceId: 1,
        sourceName: 'X',
        skipLocator: false,
      });
      expect(next).toBe(state);
    });

    it('source_selected from identify → no-op', () => {
      const state = identifyState();
      const next = transition(state, { type: 'source_selected', source });
      expect(next).toBe(state);
    });

    it('source_create_started from locator → no-op', () => {
      const state: CiteState = { stage: 'locator', draft: emptyDraft() };
      const next = transition(state, { type: 'source_create_started', prefillName: 'X' });
      expect(next).toBe(state);
    });

    it('source_create_started from create → no-op', () => {
      const state: CiteState = {
        stage: 'create',
        draft: emptyDraft(),
        parent: null,
        prefillName: 'Y',
        extractionDraft: null,
      };
      const next = transition(state, { type: 'source_create_started', prefillName: 'X' });
      expect(next).toBe(state);
    });
  });

  describe('locator_submitted', () => {
    it('from locator → same stage with draft.locator updated', () => {
      const state: CiteState = {
        stage: 'locator',
        draft: { sourceId: 5, sourceName: 'X', locator: '', skipLocator: false },
      };
      const next = transition(state, { type: 'locator_submitted', locator: 'p. 42' });

      expect(next.stage).toBe('locator');
      expect(next.draft.locator).toBe('p. 42');
      expect(next.draft.sourceId).toBe(5);
    });

    it('from locator with empty locator → works (skip path)', () => {
      const state: CiteState = {
        stage: 'locator',
        draft: { sourceId: 5, sourceName: 'X', locator: '', skipLocator: false },
      };
      const next = transition(state, { type: 'locator_submitted', locator: '' });

      expect(next.stage).toBe('locator');
      expect(next.draft.locator).toBe('');
    });

    it('from search → no-op', () => {
      const state = searchState();
      const next = transition(state, { type: 'locator_submitted', locator: 'p. 1' });
      expect(next).toBe(state);
    });

    it('from identify → no-op', () => {
      const state = identifyState();
      const next = transition(state, { type: 'locator_submitted', locator: 'p. 1' });
      expect(next).toBe(state);
    });
  });
});
