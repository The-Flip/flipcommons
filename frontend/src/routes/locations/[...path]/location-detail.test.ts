import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { LocationDetailSchema } from '$lib/api/schema';
import Page from './location-detail.test-harness.svelte';

const EMPTY_DESCRIPTION = { text: '', plain: '', html: '', citations: [], attribution: null };

const BASE_LOCATION = {
  name: 'USA',
  public_id: 'usa',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'usa',
  location_type: 'country',
  expected_child_type: 'state',
  short_name: 'USA',
  code: null,
  divisions: ['state', 'city'],
  aliases: [],
  manufacturer_count: 2,
  ancestors: [],
  children: [],
  manufacturers: [
    { public_id: 'williams', name: 'Williams', model_count: 12, thumbnail_url: null },
    { public_id: 'stern', name: 'Stern', model_count: 8, thumbnail_url: null },
  ],
  description: EMPTY_DESCRIPTION,
} satisfies LocationDetailSchema;

describe('location detail SSR route', () => {
  it('renders the manufacturers heading with count when no description is present', () => {
    const { body } = render(Page, {
      props: {
        data: { profile: BASE_LOCATION },
      },
    });

    expect(body).toContain('Manufacturers (2)');
    expect(body).toContain('Williams');
  });

  it('renders the overview and references accordions when description has html and citations', () => {
    const { body } = render(Page, {
      props: {
        data: {
          profile: {
            ...BASE_LOCATION,
            description: {
              text: 'A federal republic.[1]',
              plain: 'A federal republic.',
              html: '<p>A <strong>federal</strong> republic.</p>',
              citations: [
                {
                  id: 7,
                  index: 1,
                  source_name: 'Pinball Atlas',
                  source_type: 'book',
                  author: 'Jane Example',
                  year: 2020,
                  locator: 'p. 12',
                  links: [],
                },
              ],
              attribution: null,
            },
          },
        },
      },
    });

    expect(body).toContain('Overview');
    expect(body).toContain('<strong>federal</strong>');
    expect(body).toContain('References (1)');
  });
});
