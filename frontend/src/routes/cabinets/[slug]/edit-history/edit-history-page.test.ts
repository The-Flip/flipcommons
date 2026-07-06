import type { ChangeSetSchema } from '$lib/api/schema';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';

import Harness from './edit-history-page.test-harness.svelte';

describe('cabinet edit-history page (taxonomy representative)', () => {
  it('wraps EditHistory in FocusContentShell with back link to detail and an Edit History heading', () => {
    const { body } = render(Harness, {
      props: { data: { changesets: [] } },
    });

    expect(body).toContain('href="/cabinets/standard-body"');
    expect(body).toContain('Back');
    expect(body).toContain('>Edit History</h1>');
    expect(body.toLowerCase()).toContain('no edit history yet');
  });

  it('renders a field change citation as a source link', () => {
    const changeset: ChangeSetSchema = {
      id: 1,
      attribution: {
        author: { kind: 'source', name: 'Flip Museum' },
        created_at: '2026-01-01T00:00:00Z',
      },
      note: 'only one prototype made',
      changes: [
        {
          field_name: 'year',
          claim_key: 'year',
          old_value: null,
          new_value: { raw: 1998, display: null },
          claim_id: 5,
          claim_user_id: null,
          is_active: true,
          is_winning: true,
          is_retracted: false,
          citations: [
            {
              source_name: 'Internet Pinball Database #4443',
              source_type: 'database',
              author: '',
              year: null,
              locator: '',
              slug: null,
              links: [
                {
                  url: 'https://www.ipdb.org/machine.cgi?id=4443',
                  link_type: 'reference',
                  display_name: 'ipdb.org',
                },
              ],
            },
          ],
        },
      ],
      retractions: [],
    };

    const { body } = render(Harness, { props: { data: { changesets: [changeset] } } });

    expect(body).toContain('only one prototype made');
    expect(body).toContain('Internet Pinball Database #4443');
    expect(body).toContain('href="https://www.ipdb.org/machine.cgi?id=4443"');
  });
});
