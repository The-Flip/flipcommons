import { describe, it, expect } from 'vitest';
import {
  suppressChildResults,
  emptyDraft,
  transition,
  parentContextFromSource,
  isWebSeed,
  hostFromUrl,
  urlFromQuery,
  type CitationSourceResult,
  type CiteState,
  type CitationInstanceDraft,
  type ParentContext,
  type ExtractionDraft,
  isbnFromQuery,
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
// urlFromQuery
// ---------------------------------------------------------------------------

describe('urlFromQuery', () => {
  it('returns a schemed URL verbatim', () => {
    expect(urlFromQuery('https://imdb.com/title/tt1/')).toBe('https://imdb.com/title/tt1/');
    expect(urlFromQuery('http://example.com')).toBe('http://example.com');
  });

  it('prepends https:// to a scheme-less host with a path', () => {
    expect(urlFromQuery('www.imdb.com/title/tt27714946/')).toBe(
      'https://www.imdb.com/title/tt27714946/',
    );
  });

  it('prepends https:// to a bare dotted domain', () => {
    expect(urlFromQuery('imdb.com')).toBe('https://imdb.com');
    expect(urlFromQuery('s4.american-pinball.com')).toBe('https://s4.american-pinball.com');
  });

  it('trims surrounding whitespace before deciding', () => {
    expect(urlFromQuery('  imdb.com/x  ')).toBe('https://imdb.com/x');
  });

  it('rejects plain search terms', () => {
    expect(urlFromQuery('Pinball Wizard')).toBeNull();
    expect(urlFromQuery('e.g')).toBeNull(); // single-char final label is not TLD-like
    expect(urlFromQuery('')).toBeNull();
    expect(urlFromQuery('   ')).toBeNull();
  });

  it('rejects a scheme-less candidate containing whitespace', () => {
    expect(urlFromQuery('imdb.com /title')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// parentContextFromSource
// ---------------------------------------------------------------------------

describe('hostFromUrl', () => {
  it('returns the lowercased host', () => {
    expect(hostFromUrl('https://Example.COM/a/b')).toBe('example.com');
  });

  it('strips a leading www.', () => {
    expect(hostFromUrl('https://www.newsite.com/article')).toBe('newsite.com');
  });

  it('keeps a non-www subdomain', () => {
    expect(hostFromUrl('https://blog.newsite.com/post')).toBe('blog.newsite.com');
  });

  it('returns "" for an unparseable URL', () => {
    expect(hostFromUrl('not a url')).toBe('');
  });
});

describe('isWebSeed', () => {
  it('true for a new-site web seed (no siteName, scrape failed)', () => {
    expect(isWebSeed({ kind: 'web', url: 'https://x.com/a', siteName: null, draft: null })).toBe(
      true,
    );
  });

  it('true for an existing-site web seed (siteName set)', () => {
    expect(isWebSeed({ kind: 'web', url: 'https://x.com/a', siteName: 'X', draft: null })).toBe(
      true,
    );
  });

  it('false for a book extraction seed', () => {
    const draft: ExtractionDraft = {
      name: 'A book',
      source_type: 'book',
      author: 'Author',
      publisher: 'Pub',
      year: 2009,
      isbn: '9780596517748',
    };
    expect(isWebSeed({ kind: 'extraction', draft })).toBe(false);
  });

  it('false for a manual name seed', () => {
    expect(isWebSeed({ kind: 'name', name: 'Anything' })).toBe(false);
  });
});

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
// emptyDraft
// ---------------------------------------------------------------------------

describe('emptyDraft', () => {
  it('returns a fresh empty draft', () => {
    expect(emptyDraft()).toEqual({
      sourceId: null,
      sourceName: '',
      sourceType: '',
      locator: '',
      locatorHint: '',
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

function locatorState(
  draftOverrides: Partial<CitationInstanceDraft> = {},
  ready = false,
): CiteState {
  return { stage: 'locator', draft: { ...emptyDraft(), ...draftOverrides }, ready };
}

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

    it('locator source → locator stage, not ready', () => {
      const source = makeSource({ id: 5, name: 'Concrete', skip_locator: false });
      const next = transition(searchState(), { type: 'source_selected', source });
      expect(next.stage).toBe('locator');
      expect(next.draft.sourceId).toBe(5);
      expect(next.draft.sourceName).toBe('Concrete');
      expect(next.draft.skipLocator).toBe(false);
      if (next.stage === 'locator') expect(next.ready).toBe(false);
    });

    it('skip-locator source → ready immediately (no screen)', () => {
      const source = makeSource({ id: 6, name: 'Web Child', skip_locator: true });
      const next = transition(searchState(), { type: 'source_selected', source });

      expect(next.stage).toBe('locator');
      expect(next.draft.skipLocator).toBe(true);
      if (next.stage === 'locator') expect(next.ready).toBe(true);
    });
  });

  describe('source_identified', () => {
    it('from identify → locator stage with draft updated to child', () => {
      const state = identifyState(makeParent({ id: 10 }), { sourceId: 10, sourceName: 'Parent' });
      const next = transition(state, {
        type: 'source_identified',
        sourceType: 'web',
        sourceId: 11,
        sourceName: 'Child Edition',
        skipLocator: false,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.sourceId).toBe(11);
      expect(next.draft.sourceName).toBe('Child Edition');
      expect(next.draft.skipLocator).toBe(false);
      if (next.stage === 'locator') expect(next.ready).toBe(false);
    });

    it('threads sourceType and locatorHint into the draft', () => {
      const state = identifyState();
      const next = transition(state, {
        type: 'source_identified',
        sourceType: 'video',
        sourceId: 13,
        sourceName: 'YouTube #dQw4w9WgXcQ',
        skipLocator: false,
        locatorHint: '1:35',
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.sourceType).toBe('video');
      expect(next.draft.locatorHint).toBe('1:35');
      // The hint is a prefill, not a submitted locator — it must not complete
      // the flow past the locator stage.
      expect(next.draft.locator).toBe('');
      if (next.stage === 'locator') expect(next.ready).toBe(false);
    });

    it('skip-locator child → ready immediately', () => {
      const state = identifyState();
      const next = transition(state, {
        type: 'source_identified',
        sourceType: 'web',
        sourceId: 12,
        sourceName: 'IPDB Machine 4836',
        skipLocator: true,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.skipLocator).toBe(true);
      if (next.stage === 'locator') expect(next.ready).toBe(true);
    });

    it('from search → locator stage (recognition path)', () => {
      const state = searchState();
      const next = transition(state, {
        type: 'source_identified',
        sourceType: 'web',
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

  describe('create_started', () => {
    const draft: ExtractionDraft = {
      name: 'Learning Python',
      source_type: 'book',
      author: 'Mark Lutz',
      publisher: "O'Reilly Media",
      year: 2009,
      isbn: '9780596517748',
    };

    it('name seed from search → create with parent: null', () => {
      const state = searchState();
      const next = transition(state, {
        type: 'create_started',
        seed: { kind: 'name', name: 'New Source' },
      });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.parent).toBeNull();
        expect(next.seed).toEqual({ kind: 'name', name: 'New Source' });
      }
    });

    it('name seed from identify → create with parent carried over', () => {
      const parent = makeParent({ id: 10, name: 'Book Series' });
      const state = identifyState(parent);
      const next = transition(state, {
        type: 'create_started',
        seed: { kind: 'name', name: 'New Edition' },
      });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.parent).toEqual(parent);
        expect(next.seed).toEqual({ kind: 'name', name: 'New Edition' });
      }
    });

    it('extraction seed from search → create carrying the draft, parent null', () => {
      const state = searchState();
      const next = transition(state, {
        type: 'create_started',
        seed: { kind: 'extraction', draft },
      });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.parent).toBeNull();
        expect(next.seed).toEqual({ kind: 'extraction', draft });
      }
    });

    it('web seed from search → create carrying the seed, parent null', () => {
      // The web/authored split is a rendering concern (the orchestrator picks the
      // component via isWebSeed); the reducer routes every create to `create`.
      const state = searchState();
      const seed = {
        kind: 'web',
        url: 'https://example.com/page',
        siteName: null,
        draft: null,
      } as const;
      const next = transition(state, { type: 'create_started', seed });

      expect(next.stage).toBe('create');
      if (next.stage === 'create') {
        expect(next.parent).toBeNull();
        expect(next.seed).toEqual(seed);
      }
    });
  });

  describe('source_created', () => {
    it('→ locator stage with draft updated to new source, not ready', () => {
      const state: CiteState = {
        stage: 'create',
        draft: emptyDraft(),
        parent: null,
        seed: { kind: 'name', name: 'New Source' },
      };
      const next = transition(state, {
        type: 'source_created',
        sourceType: 'web',
        sourceId: 50,
        sourceName: 'New Source',
        skipLocator: false,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.sourceId).toBe(50);
      expect(next.draft.sourceName).toBe('New Source');
      expect(next.draft.skipLocator).toBe(false);
      if (next.stage === 'locator') expect(next.ready).toBe(false);
    });

    it('skip-locator create → ready immediately', () => {
      const state: CiteState = {
        stage: 'create',
        draft: emptyDraft(),
        parent: makeParent(),
        seed: { kind: 'name', name: 'Web Child' },
      };
      const next = transition(state, {
        type: 'source_created',
        sourceType: 'web',
        sourceId: 51,
        sourceName: 'Web Child',
        skipLocator: true,
      });

      expect(next.stage).toBe('locator');
      expect(next.draft.skipLocator).toBe(true);
      if (next.stage === 'locator') expect(next.ready).toBe(true);
    });
  });

  describe('invalid transitions', () => {
    const source = makeSource({ id: 1 });
    const draft: ExtractionDraft = {
      name: 'Learning Python',
      source_type: 'book',
      author: 'Mark Lutz',
      publisher: "O'Reilly Media",
      year: 2009,
      isbn: '9780596517748',
    };

    it('source_created from search → no-op', () => {
      const state = searchState();
      const next = transition(state, {
        type: 'source_created',
        sourceType: 'web',
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

    it('create_started from locator → no-op', () => {
      const state = locatorState();
      const next = transition(state, {
        type: 'create_started',
        seed: { kind: 'extraction', draft },
      });
      expect(next).toBe(state);
    });

    it('create_started from create → no-op', () => {
      const state: CiteState = {
        stage: 'create',
        draft: emptyDraft(),
        parent: null,
        seed: { kind: 'name', name: 'Y' },
      };
      const next = transition(state, { type: 'create_started', seed: { kind: 'name', name: 'X' } });
      expect(next).toBe(state);
    });
  });

  describe('locator_submitted', () => {
    it('carries the locator into the draft and marks ready', () => {
      const state = locatorState({ sourceId: 5, sourceName: 'X', sourceType: 'book' });
      const next = transition(state, { type: 'locator_submitted', locator: 'p. 42' });

      expect(next.stage).toBe('locator');
      expect(next.draft.locator).toBe('p. 42');
      expect(next.draft.sourceId).toBe(5);
      if (next.stage === 'locator') expect(next.ready).toBe(true);
    });

    it('empty locator still completes (skip path) — the stage is the signal, not the data', () => {
      // Before the reducer owned completion, locator === '' was ambiguous
      // ("not entered yet" vs "skipped"). Now the submit action itself
      // completes the flow, whatever the values.
      const state = locatorState({ sourceId: 5, sourceName: 'X', sourceType: 'book' });
      const next = transition(state, { type: 'locator_submitted', locator: '' });

      expect(next.stage).toBe('locator');
      expect(next.draft.locator).toBe('');
      if (next.stage === 'locator') expect(next.ready).toBe(true);
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

  // -------------------------------------------------------------------------
  // End-to-end flow sequences: the reducer models the whole path, so these
  // assert stage order rather than per-action plumbing.
  // -------------------------------------------------------------------------

  describe('flow sequences', () => {
    const locatorSource = makeSource({ id: 5, name: 'Book', skip_locator: false });
    const skipLocatorSource = makeSource({ id: 6, name: 'IPDB #4836', skip_locator: true });

    it('locator source: search → locator → ready', () => {
      let state = searchState();
      state = transition(state, { type: 'source_selected', source: locatorSource });
      expect(state).toMatchObject({ stage: 'locator', ready: false });

      state = transition(state, { type: 'locator_submitted', locator: 'p. 42' });
      expect(state).toMatchObject({ stage: 'locator', ready: true });
      expect(state.draft).toMatchObject({ locator: 'p. 42' });
    });

    it('skip-locator source: search → ready in one step', () => {
      let state = searchState();
      state = transition(state, { type: 'source_selected', source: skipLocatorSource });
      expect(state).toMatchObject({ stage: 'locator', ready: true });
      expect(state.draft).toMatchObject({ sourceId: 6, locator: '' });
    });
  });
});

describe('isbnFromQuery', () => {
  it('accepts a whole-input ISBN shape-only (the lenient historical contract)', () => {
    expect(isbnFromQuery('978-0-596-51774-8')).toBe('9780596517748');
    // Bad check digit still passes whole-input — Open Library fails it loudly.
    expect(isbnFromQuery('0596517741')).toBe('0596517741');
  });

  it('finds a checksum-valid ISBN embedded in pasted text', () => {
    expect(isbnFromQuery('Pinball Compendium 978-0764325847 first edition')).toBe('9780764325847');
    expect(isbnFromQuery('see ISBN 0596517742 for details')).toBe('0596517742');
  });

  it('rejects embedded digit runs that fail the checksum', () => {
    expect(isbnFromQuery('call 1234567890 for details')).toBeNull();
  });

  it('never mines ISBNs out of URLs — the deliverer path owns those', () => {
    expect(isbnFromQuery('https://example.com/files/0596517742.pdf')).toBeNull();
    expect(isbnFromQuery('example.com/files/0596517742.pdf')).toBeNull();
  });

  it('ignores tokens butted against longer alphanumeric runs', () => {
    expect(isbnFromQuery('id 90596517742 ref')).toBeNull();
  });
});
