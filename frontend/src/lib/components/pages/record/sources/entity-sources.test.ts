import { beforeEach, describe, expect, it } from 'vitest';

import type { ClaimSchema } from '$lib/api/schema';
import { buildSourcesView } from './entity-sources';

/** Attribution shorthand — source *name* asserting at *created_at*. */
function by(name: string, created_at: string): ClaimSchema['attribution'] {
  return { author: { kind: 'source', name }, created_at };
}

function claim(overrides: Partial<ClaimSchema> & Pick<ClaimSchema, 'field_name'>): ClaimSchema {
  return {
    claim_key: overrides.field_name,
    value: { raw: null },
    attribution: by('IPDB', '2026-04-07T00:00:00Z'),
    is_winner: false,
    citations: [],
    ...overrides,
  };
}

// Reset per test so ids never depend on how many tests ran first — otherwise
// a suite-wide run and a `.only` run disagree.
let nextCitationId = 0;
beforeEach(() => {
  nextCitationId = 0;
});

function citation(source_name: string, locator = '', root_name: string | null = null) {
  return {
    id: (nextCitationId += 1),
    source_name,
    root_name,
    source_type: 'web',
    author: '',
    year: null,
    locator,
    quote: '',
    links: [],
  };
}

describe('buildSourcesView', () => {
  it('consolidates a value asserted by several actors into one entry', () => {
    const { fields } = buildSourcesView([
      claim({
        field_name: 'year',
        value: { raw: 1997 },
        is_winner: true,
        attribution: by('Flipcommons Catalog', '2026-04-08T00:00:00Z'),
      }),
      claim({ field_name: 'year', value: { raw: 1997 } }),
    ]);

    const entry = fields[0].slots[0].winner;
    expect(fields[0].slots[0].others).toHaveLength(0);
    expect(entry.supporters.map((a) => (a.author.kind === 'source' ? a.author.name : ''))).toEqual([
      'Flipcommons Catalog',
      'IPDB',
    ]);
    expect(entry.isWinner).toBe(true);
  });

  it('lists conflicting values under one slot, winner first', () => {
    const { fields } = buildSourcesView([
      claim({ field_name: 'year', value: { raw: 1998 } }),
      claim({
        field_name: 'year',
        value: { raw: 1997 },
        is_winner: true,
        attribution: {
          author: { kind: 'user', username: 'editor' },
          created_at: '2026-04-09T00:00:00Z',
        },
      }),
    ]);

    const slot = fields[0].slots[0];
    expect(slot.winner.value.raw).toBe(1997);
    expect(slot.others.map((v) => v.value.raw)).toEqual([1998]);
  });

  it('keeps a multi-valued field as separate uncontested slots', () => {
    // Two themes are two related rows, not two sources disagreeing — the
    // related row, not the field name, is what competes.
    const { fields } = buildSourcesView([
      claim({ field_name: 'theme', claim_key: 'theme|theme:1', is_winner: true }),
      claim({ field_name: 'theme', claim_key: 'theme|theme:2', is_winner: true }),
    ]);

    expect(fields[0].slots).toHaveLength(2);
    expect(fields[0].slots.every((slot) => slot.others.length === 0)).toBe(true);
  });

  it('sorts fields by most recent claim, not by whether they are contested', () => {
    const { fields } = buildSourcesView([
      // 'year' is contested but stale; 'name' is uncontested and newer.
      claim({ field_name: 'year', value: { raw: 1997 }, is_winner: true }),
      claim({
        field_name: 'year',
        value: { raw: 1998 },
        attribution: by('OPDB', '2026-04-06T00:00:00Z'),
      }),
      claim({
        field_name: 'name',
        value: { raw: 'MM' },
        is_winner: true,
        attribution: by('OPDB', '2026-05-01T00:00:00Z'),
      }),
    ]);

    expect(fields.map((f) => f.field)).toEqual(['name', 'year']);
  });

  it('sorts slots by most recent claim, not by whether they are contested', () => {
    const { fields } = buildSourcesView([
      // theme:1 is contested but stale; theme:2 is uncontested and newer.
      claim({
        field_name: 'theme',
        claim_key: 'theme|theme:1',
        value: { raw: 'Medieval' },
        is_winner: true,
      }),
      claim({
        field_name: 'theme',
        claim_key: 'theme|theme:1',
        value: { raw: 'Fantasy' },
        attribution: by('OPDB', '2026-04-06T00:00:00Z'),
      }),
      claim({
        field_name: 'theme',
        claim_key: 'theme|theme:2',
        value: { raw: 'Dragons' },
        is_winner: true,
        attribution: by('OPDB', '2026-05-01T00:00:00Z'),
      }),
    ]);

    expect(fields[0].slots.map((s) => s.claimKey)).toEqual(['theme|theme:2', 'theme|theme:1']);
  });

  it('pools and dedupes citations across the actors backing one value', () => {
    const { fields, references } = buildSourcesView([
      claim({
        field_name: 'year',
        value: { raw: 1997 },
        is_winner: true,
        citations: [citation('Williams Flyer', 'p. 2'), citation('IPDB')],
      }),
      claim({
        field_name: 'year',
        value: { raw: 1997 },
        attribution: by('OPDB', '2026-04-06T00:00:00Z'),
        citations: [citation('Williams Flyer', 'p. 2')],
      }),
    ]);

    const entry = fields[0].slots[0].winner;
    expect(entry.footnotes.map((f) => f.index)).toEqual([1, 2]);
    expect(references.map((c) => c.source_name)).toEqual(['Williams Flyer', 'IPDB']);
  });

  it('keeps identically named children of different parents apart', () => {
    // A child's name need not repeat its parent, so two works can each hold a
    // "Vol. 2". Without the parent in the key they would pool into one.
    const { references } = buildSourcesView([
      claim({
        field_name: 'year',
        value: { raw: 1997 },
        is_winner: true,
        citations: [
          citation('Vol. 2', 'p. 42', 'The Encyclopedia of Pinball'),
          citation('Vol. 2', 'p. 42', 'The Pinball Compendium'),
        ],
      }),
    ]);

    expect(references.map((c) => c.root_name)).toEqual([
      'The Encyclopedia of Pinball',
      'The Pinball Compendium',
    ]);
  });

  it('numbers citations in page order and reuses the number on repeat', () => {
    const { fields, references } = buildSourcesView([
      claim({
        field_name: 'year',
        value: { raw: 1997 },
        is_winner: true,
        citations: [citation('Shared')],
      }),
      claim({
        field_name: 'year',
        value: { raw: 1998 },
        citations: [citation('Other')],
      }),
      claim({ field_name: 'name', is_winner: true, citations: [citation('Shared')] }),
    ]);

    expect(fields.map((f) => f.field)).toEqual(['year', 'name']);
    expect(fields[0].slots[0].winner.footnotes.map((f) => f.index)).toEqual([1]);
    expect(fields[0].slots[0].others[0].footnotes.map((f) => f.index)).toEqual([2]);
    expect(fields[1].slots[0].winner.footnotes.map((f) => f.index)).toEqual([1]);
    expect(references.map((c) => c.source_name)).toEqual(['Shared', 'Other']);
  });

  it("orders a value's citation numbers ascending, not first-seen order", () => {
    const { fields, references } = buildSourcesView([
      claim({ field_name: 'year', is_winner: true, citations: [citation('First')] }),
      claim({
        field_name: 'name',
        is_winner: true,
        // 'Second' is new here (gets 2); 'First' already carries 1.
        citations: [citation('Second'), citation('First')],
        attribution: by('IPDB', '2026-04-06T00:00:00Z'),
      }),
    ]);

    const entry = fields[1].slots[0].winner;
    expect(entry.footnotes.map((f) => f.index)).toEqual([1, 2]);
    expect(references.map((c) => c.source_name)).toEqual(['First', 'Second']);
  });

  it('routes a markdown value’s inline citation to its marker, not a footnote', () => {
    const { fields, references } = buildSourcesView([
      claim({
        field_name: 'description',
        value: {
          raw: 'Launched in 1966. [[cite:id:7]]',
          display: { kind: 'markdown', text: 'Launched in 1966. [[cite:flyer-p2]]' },
        },
        is_winner: true,
        citations: [{ ...citation('Williams Flyer', 'p. 2'), slug: 'flyer-p2' }],
      }),
    ]);

    const entry = fields[0].slots[0].winner;
    // Positioned by its marker, so it must not also trail the value.
    expect([...entry.citeIndexes]).toEqual([['flyer-p2', 1]]);
    expect(entry.footnotes.map((f) => f.index)).toEqual([]);
    expect(references).toHaveLength(1);
  });

  it('footnotes a slug-bearing citation when the value has no marker to hold it', () => {
    const { fields } = buildSourcesView([
      claim({
        field_name: 'name',
        value: { raw: 'MM' },
        is_winner: true,
        citations: [{ ...citation('Williams Flyer'), slug: 'flyer' }],
      }),
    ]);

    const entry = fields[0].slots[0].winner;
    expect(entry.citeIndexes.size).toBe(0);
    expect(entry.footnotes.map((f) => f.index)).toEqual([1]);
  });

  it('marks markdown values as prose and everything else as not', () => {
    const { fields } = buildSourcesView([
      claim({
        field_name: 'description',
        value: { raw: 'Long copy', display: { kind: 'markdown', text: 'Long copy' } },
        is_winner: true,
      }),
      claim({ field_name: 'year', value: { raw: 1997 }, is_winner: true }),
    ]);

    const byField = Object.fromEntries(fields.map((f) => [f.field, f.slots[0].winner.isProse]));
    expect(byField).toEqual({ description: true, year: false });
  });

  it('gives every value a uid unique across the page', () => {
    const { fields } = buildSourcesView([
      // Same value text under two different slots of one field, plus a rival
      // under one of them — the three must not collide.
      claim({ field_name: 'theme', claim_key: 'theme|theme:1', value: { raw: 'X' } }),
      claim({ field_name: 'theme', claim_key: 'theme|theme:2', value: { raw: 'X' } }),
      claim({ field_name: 'theme', claim_key: 'theme|theme:2', value: { raw: 'Y' } }),
    ]);

    const uids = fields
      .flatMap((f) => f.slots)
      .flatMap((slot) => [slot.winner, ...slot.others])
      .map((entry) => entry.uid);
    expect(uids).toHaveLength(3);
    expect(new Set(uids).size).toBe(3);
  });

  it('merges evidence reaching a value both attached and inline, keeping the marker', () => {
    // The same instance can be attached to the claim *and* cited from its
    // text; that is one citation, positioned where the marker sits.
    const { fields, references } = buildSourcesView([
      claim({
        field_name: 'description',
        value: {
          raw: 'Text [[cite:id:7]]',
          display: { kind: 'markdown', text: 'Text [[cite:flyer-p2]]' },
        },
        is_winner: true,
        citations: [
          citation('Williams Flyer', 'p. 2'),
          { ...citation('Williams Flyer', 'p. 2'), slug: 'flyer-p2' },
        ],
      }),
    ]);

    const entry = fields[0].slots[0].winner;
    expect(references).toHaveLength(1);
    expect([...entry.citeIndexes]).toEqual([['flyer-p2', 1]]);
    expect(entry.footnotes.map((f) => f.index)).toEqual([]);
  });

  it('points every marker sharing a number at the id that number lists', () => {
    // The same evidence recorded twice is two instance ids but one reference
    // number. The tooltip resolves a marker by id against `references`, which
    // holds one entry per number — so a marker citing its own id instead of
    // the entry's would resolve to nothing and go inert.
    const { fields, references } = buildSourcesView([
      claim({
        field_name: 'description',
        value: {
          raw: 'Text [[cite:id:10]]',
          display: { kind: 'markdown', text: 'Text [[cite:flyer]]' },
        },
        is_winner: true,
        citations: [{ ...citation('Williams Flyer', 'p. 2'), id: 10, slug: 'flyer' }],
      }),
      claim({
        field_name: 'year',
        value: { raw: 1997 },
        is_winner: true,
        citations: [{ ...citation('Williams Flyer', 'p. 2'), id: 57 }],
        attribution: by('OPDB', '2026-04-06T00:00:00Z'),
      }),
    ]);

    expect(references).toHaveLength(1);
    const listed = references[0].id;
    const [prose, scalar] = fields.map((f) => f.slots[0].winner);
    expect([...prose.citeIds.values()]).toEqual([listed]);
    expect(scalar.footnotes.map((f) => f.id)).toEqual([listed]);
  });
});
