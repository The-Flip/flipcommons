import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';

import type { ChangeSetSchema, ClaimCitationSchema } from '$lib/api/schema';
import Harness from './edit-history-page.test-harness.svelte';

function makeCitation(over: Partial<ClaimCitationSchema>): ClaimCitationSchema {
  return {
    id: 1,
    source_name: 'Some Source',
    source_type: 'web',
    author: '',
    year: null,
    locator: '',
    quote: '',
    slug: null,
    links: [],
    ...over,
  };
}

function makeChangeset(over: Partial<ChangeSetSchema>): ChangeSetSchema {
  return {
    id: 1,
    attribution: {
      author: { kind: 'user', username: 'kim' },
      created_at: '2026-07-01T00:00:00+00:00',
    },
    note: '',
    changes: [],
    retractions: [],
    capabilities: { 'changeset.undo': false },
    ...over,
  };
}

describe('manufacturer edit-history page', () => {
  it('wraps EditHistory in FocusContentShell with back link to detail and an Edit History heading', () => {
    const { body } = render(Harness, {
      props: { data: { changesets: [] } },
    });

    expect(body).toContain('href="/manufacturers/williams"');
    expect(body).toContain('Back');
    expect(body).toContain('>Edit History</h1>');
    expect(body.toLowerCase()).toContain('no edit history yet');
  });

  it('renders inline [[cite:]] tokens as numbered superscripts with a citations footer', () => {
    const changeset = makeChangeset({
      changes: [
        {
          field_name: 'description',
          claim_key: 'description',
          old_value: null,
          new_value: {
            raw: 'Founded in 2024.[[cite:id:1]] Debuted at Expo.[[cite:id:2]]',
            display: {
              kind: 'markdown',
              text: 'Founded in 2024.[[cite:bbb]] Debuted at Expo.[[cite:aaa]]',
            },
          },
          claim_id: 10,
          claim_user_id: 1,
          is_active: true,
          is_winning: true,
          is_retracted: false,
          citations: [
            makeCitation({
              slug: 'aaa',
              source_name: 'The Toy Book',
              author: 'Ryan Vincent',
              year: 2024,
              links: [
                {
                  url: 'https://toybook.com/wonderland/',
                  link_type: 'reference',
                  display_name: 'toybook.com',
                },
              ],
            }),
            makeCitation({ slug: 'bbb', source_name: 'Kickstarter' }),
          ],
        },
      ],
    });

    const { body } = render(Harness, { props: { data: { changesets: [changeset] } } });

    // Tokens become markers, numbered by document order: bbb first.
    expect(body).not.toContain('[[cite:');
    expect(body).toContain('>[1]</sup>');
    expect(body).toContain('>[2]</sup>');
    // Footer lists both sources; the numbered Kickstarter row comes first.
    expect(body).toContain('Kickstarter');
    expect(body).toContain('The Toy Book');
    expect(body.indexOf('Kickstarter')).toBeLessThan(body.indexOf('The Toy Book'));
    expect(body).toContain('Ryan Vincent, 2024');
    expect(body).toContain('href="https://toybook.com/wonderland/"');
  });

  it('renders attached (scalar) citations as unnumbered footer rows', () => {
    const changeset = makeChangeset({
      changes: [
        {
          field_name: 'name',
          claim_key: 'name',
          old_value: null,
          new_value: { raw: 'Wonderland Amusements', display: null },
          claim_id: 11,
          claim_user_id: 1,
          is_active: true,
          is_winning: true,
          is_retracted: false,
          citations: [
            makeCitation({
              source_name: 'IPDB entry',
              source_type: 'database',
              links: [
                {
                  url: 'https://ipdb.org/1',
                  link_type: 'reference',
                  display_name: 'ipdb.org',
                },
              ],
            }),
          ],
        },
      ],
    });

    const { body } = render(Harness, { props: { data: { changesets: [changeset] } } });

    expect(body).toContain('IPDB entry');
    expect(body).toContain('href="https://ipdb.org/1"');
    expect(body).not.toContain('</sup>');
  });
});
