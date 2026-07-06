/** Tests for inline cite-marker helpers used by edit history. */

import { describe, expect, it } from 'vitest';
import {
  assignCiteIndexes,
  extractCiteSlugs,
  splitCiteMarkers,
  substituteCiteMarkers,
} from './cite-markers';

describe('extractCiteSlugs', () => {
  it('returns slugs in document order, deduped', () => {
    const text = 'A.[[cite:bbb]] B.[[cite:aaa]] C.[[cite:bbb]]';
    expect(extractCiteSlugs(text)).toEqual(['bbb', 'aaa']);
  });

  it('ignores storage-form tokens', () => {
    expect(extractCiteSlugs('Broken.[[cite:id:42]] Ok.[[cite:xyz]]')).toEqual(['xyz']);
  });

  it('returns empty for text without tokens', () => {
    expect(extractCiteSlugs('No citations here.')).toEqual([]);
  });
});

describe('assignCiteIndexes', () => {
  it('numbers by first appearance in the new text', () => {
    const indexes = assignCiteIndexes('X.[[cite:bbb]] Y.[[cite:aaa]]', '', new Set(['aaa', 'bbb']));
    expect([...indexes.entries()]).toEqual([
      ['bbb', 1],
      ['aaa', 2],
    ]);
  });

  it('continues numbering with old-only slugs after new-text ones', () => {
    const indexes = assignCiteIndexes(
      'Kept.[[cite:kkk]]',
      'Removed.[[cite:rrr]] Kept.[[cite:kkk]]',
      new Set(['kkk', 'rrr']),
    );
    expect(indexes.get('kkk')).toBe(1);
    expect(indexes.get('rrr')).toBe(2);
  });

  it('skips slugs without citation metadata', () => {
    const indexes = assignCiteIndexes('A.[[cite:ghost]] B.[[cite:real]]', '', new Set(['real']));
    expect(indexes.has('ghost')).toBe(false);
    expect(indexes.get('real')).toBe(1);
  });
});

describe('substituteCiteMarkers', () => {
  it('rewrites tokens to their assigned markers', () => {
    const indexes = new Map([
      ['bbb', 1],
      ['aaa', 2],
    ]);
    expect(substituteCiteMarkers('X.[[cite:bbb]] Y.[[cite:aaa]]', indexes)).toBe('X.[1] Y.[2]');
  });

  it('renders unassigned slugs as [?]', () => {
    expect(substituteCiteMarkers('X.[[cite:ghost]]', new Map())).toBe('X.[?]');
  });

  it('leaves storage-form tokens untouched', () => {
    expect(substituteCiteMarkers('Broken.[[cite:id:42]]', new Map())).toBe('Broken.[[cite:id:42]]');
  });
});

describe('splitCiteMarkers', () => {
  it('splits text runs from markers', () => {
    expect(splitCiteMarkers('veterans[1] and CEOs.[2]')).toEqual([
      { type: 'text', text: 'veterans' },
      { type: 'marker', text: '[1]' },
      { type: 'text', text: ' and CEOs.' },
      { type: 'marker', text: '[2]' },
    ]);
  });

  it('treats [?] as a marker', () => {
    expect(splitCiteMarkers('x[?]')).toEqual([
      { type: 'text', text: 'x' },
      { type: 'marker', text: '[?]' },
    ]);
  });

  it('returns one text part when there are no markers', () => {
    expect(splitCiteMarkers('plain prose')).toEqual([{ type: 'text', text: 'plain prose' }]);
  });
});
