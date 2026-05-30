import { render } from 'svelte/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { pageState, authState } = vi.hoisted(() => ({
  pageState: {
    params: { slug: 'williams' },
    url: new URL('http://localhost:5173/manufacturers/williams'),
  },
  authState: { isAuthenticated: false },
}));

vi.mock('$app/state', () => ({
  page: pageState,
}));

vi.mock('$lib/auth.svelte', () => ({
  auth: {
    get isAuthenticated() {
      return authState.isAuthenticated;
    },
    load: vi.fn(),
  },
}));

import Harness from './layout.test-harness.svelte';
import type { ManufacturerDetailSchema } from '$lib/api/schema';

const MOCK_MANUFACTURER = {
  name: 'Williams',
  public_id: 'williams',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'williams',
  description: {
    text: 'Historic manufacturer [1].',
    html: '<p>Historic manufacturer.</p>',
    plain: 'Historic manufacturer.',
    citations: [],
    attribution: null,
  },
  year_start: 1985,
  year_end: 1999,
  logo_url: null,
  website: 'https://williams.example',
  entities: [
    {
      name: 'Williams Electronics',
      public_id: 'williams-electronics',
      year_start: 1985,
      year_end: 1999,
      locations: [],
    },
  ],
  titles: [],
  systems: [],
  persons: [],
  uploaded_media: [],
} satisfies ManufacturerDetailSchema;

describe('manufacturer layout', () => {
  beforeEach(() => {
    pageState.params.slug = 'williams';
    pageState.url = new URL('http://localhost:5173/manufacturers/williams');
    authState.isAuthenticated = false;
  });

  it('renders the action bar without the legacy tab navigation on the detail route', () => {
    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, jsonLd: {} } },
    });

    expect(body).toContain('History');
    expect(body).not.toContain('>Back<');
    expect(body).not.toContain('Page sections');
  });

  it('renders a Back link on media subroutes', () => {
    pageState.url = new URL('http://localhost:5173/manufacturers/williams/media');

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, jsonLd: {} } },
    });

    expect(body).toContain('>Back<');
    expect(body).toContain('/manufacturers/williams');
  });

  it('strips the detail shell on sources subroutes (focus mode)', () => {
    pageState.url = new URL('http://localhost:5173/manufacturers/williams/sources');

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, jsonLd: {} } },
    });

    expect(body).toContain('Child content');
    expect(body).not.toContain('History');
    expect(body).not.toContain('Page sections');
  });

  it('strips the detail shell on edit-history subroutes (focus mode)', () => {
    pageState.url = new URL('http://localhost:5173/manufacturers/williams/edit-history');

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, jsonLd: {} } },
    });

    expect(body).toContain('Child content');
    expect(body).not.toContain('History');
  });

  it('renders a direct edit link on the Links sidebar section when authenticated', () => {
    authState.isAuthenticated = true;

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, jsonLd: {} } },
    });

    expect(body).toContain('Links');
    expect(body).toContain('>edit<');
  });
});
