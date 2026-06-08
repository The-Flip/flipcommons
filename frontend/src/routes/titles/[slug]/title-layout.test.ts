import { render } from 'svelte/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { pageState, authState } = vi.hoisted(() => ({
  pageState: {
    params: { slug: 'medieval-madness' },
    url: new URL('http://localhost:5173/titles/medieval-madness'),
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
import type { TitleDetailSchema } from '$lib/api/schema';

const MOCK_TITLE = {
  name: 'Medieval Madness',
  public_id: 'medieval-madness',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'medieval-madness',
  abbreviations: [],
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  needs_review: false,
  needs_review_notes: '',
  review_links: [],
  hero_image_url: null,
  franchise: null,
  machines: [
    {
      name: 'Medieval Madness',
      public_id: 'medieval-madness',
      year: 1997,
      manufacturer: { name: 'Williams', public_id: 'williams' },
      technology_generation_name: 'Solid State',
      thumbnail_url: null,
      variants: [],
    },
  ],
  series: null,
  credits: [],
  agreed_specs: { themes: [], gameplay_features: [], reward_types: [], tags: [] },
  related_titles: [],
  media: [],
  opdb_id: null,
  fandom_page_id: null,
  model_detail: null,
} satisfies TitleDetailSchema;

describe('title layout', () => {
  beforeEach(() => {
    pageState.params.slug = 'medieval-madness';
    pageState.url = new URL('http://localhost:5173/titles/medieval-madness');
    authState.isAuthenticated = false;
  });

  it('omits the Back link on the detail route', () => {
    const { body } = render(Harness, {
      props: { data: { profile: MOCK_TITLE } },
    });

    expect(body).toContain('History');
    expect(body).not.toContain('>Back<');
  });

  it('renders the agreed production status row (backend pre-suppresses produced)', () => {
    const withStatus = {
      ...MOCK_TITLE,
      agreed_specs: {
        ...MOCK_TITLE.agreed_specs,
        production_status: { name: 'Unreleased', public_id: 'unreleased' },
      },
    } satisfies TitleDetailSchema;

    const { body } = render(Harness, {
      props: { data: { profile: withStatus } },
    });

    expect(body).toContain('Production status');
    expect(body).toContain('/production-statuses/unreleased');
  });

  it('strips the detail shell on sources subroutes (focus mode)', () => {
    pageState.url = new URL('http://localhost:5173/titles/medieval-madness/sources');

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_TITLE } },
    });

    // Layout renders only the child in focus mode; chrome is gone.
    expect(body).toContain('Child content');
    expect(body).not.toContain('History');
    expect(body).not.toContain('Sources');
    expect(body).not.toContain('Edit');
  });

  it('strips the detail shell on edit-history subroutes (focus mode)', () => {
    pageState.url = new URL('http://localhost:5173/titles/medieval-madness/edit-history');

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_TITLE } },
    });

    expect(body).toContain('Child content');
    expect(body).not.toContain('History');
  });

  it('renders History and Sources as menu triggers on single-Model titles', () => {
    // On single-Model titles the action bar swaps the plain History link and
    // the existing "Tools" Sources menu for two-item dropdowns that surface
    // the Model's audit pages alongside the Title's. Menu items themselves
    // render in a portal on click and aren't observable via SSR — those are
    // covered by EditSectionMenu.dom.test.ts. Here we verify the layout
    // selects the menu shape instead of the plain link when model_detail is
    // populated.
    pageState.params.slug = 'doctor-who';
    pageState.url = new URL('http://localhost:5173/titles/doctor-who');

    const singleModelTitle = {
      ...MOCK_TITLE,
      name: 'Doctor Who',
      public_id: 'doctor-who',
      slug: 'doctor-who',
      model_detail: {
        name: 'Doctor Who',
        public_id: 'doctor-who-1992',
        last_modified: '2026-01-01T00:00:00Z',
        slug: 'doctor-who-1992',
        description: { text: '', html: '', plain: '', citations: [], attribution: null },
        abbreviations: [],
        extra_data: {},
        credits: [],
        uploaded_media: [],
        variant_features: [],
        variants: [],
        themes: [],
        gameplay_features: [],
        tags: [],
        reward_types: [],
        variant_siblings: [],
        conversions: [],
        remakes: [],
        title_models: [],
        production_quantity: '',
        title: { name: 'Doctor Who', public_id: 'doctor-who' },
      },
    } satisfies TitleDetailSchema;

    const { body } = render(Harness, {
      props: { data: { profile: singleModelTitle } },
    });

    // Two ActionMenu triggers: History and Sources. (Multi-Model titles have
    // just one — the Sources/Tools menu.)
    const triggerCount = (body.match(/aria-haspopup="menu"/g) ?? []).length;
    expect(triggerCount).toBe(2);

    // The plain "<a href=…/edit-history>History" link from the multi-Model
    // shape is suppressed when the menu takes over.
    expect(body).not.toMatch(/<a[^>]+href="[^"]*\/edit-history"[^>]*>\s*History/);
  });

  it('renders direct edit links on editable title sidebar sections when authenticated', () => {
    authState.isAuthenticated = true;

    const { body } = render(Harness, {
      props: {
        data: {
          profile: {
            ...MOCK_TITLE,
            franchise: { name: 'Williams Classics', public_id: 'williams-classics' },
          } satisfies TitleDetailSchema,
        },
      },
    });

    expect(body).toContain('Franchise');
    expect(body).toContain('>edit<');
  });
});
