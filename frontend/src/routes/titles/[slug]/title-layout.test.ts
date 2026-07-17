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
import { makeModelDetail, makeTitleDetail } from '$lib/api/detail-fixtures';

const MOCK_TITLE = makeTitleDetail({
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
});

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
      model_detail: makeModelDetail({
        name: 'Doctor Who',
        public_id: 'doctor-who-1992',
        slug: 'doctor-who-1992',
        title: { name: 'Doctor Who', public_id: 'doctor-who' },
      }),
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

  it('renders model↔model lineage in the sidebar for a single-model title', () => {
    // A bootlegged/original single-model title must show its lineage (the "of
    // what") in the sidebar, co-located with the specs/tag — not buried in a
    // main-content accordion. Sidebar bodies render server-side (unlike the
    // lazy accordions), so both heading and target link are asserted here.
    pageState.params.slug = 'video-pinball';
    pageState.url = new URL('http://localhost:5173/titles/video-pinball');

    const singleModelTitle = {
      ...MOCK_TITLE,
      name: 'Video Pinball',
      public_id: 'video-pinball',
      slug: 'video-pinball',
      model_detail: makeModelDetail({
        name: 'Video Pinball',
        public_id: 'video-pinball',
        slug: 'video-pinball',
        title: { name: 'Video Pinball', public_id: 'video-pinball' },
        relationships: [
          {
            relationship_type: 'copy',
            license_status: 'unlicensed',
            target_machine: { name: 'Jungle Life', public_id: 'jungle-life', year: 1978 },
            target_label: '',
          },
        ],
        inbound_relationships: [
          {
            relationship_type: 'copy',
            license_status: 'unlicensed',
            source_machine: { name: 'Rugby', public_id: 'rugby-sidam', year: 1979 },
          },
        ],
      }),
    } satisfies TitleDetailSchema;

    const { body } = render(Harness, {
      props: { data: { profile: singleModelTitle } },
    });

    expect(body).toContain('Bootleg of');
    expect(body).toContain('/models/jungle-life');
    expect(body).toContain('Bootlegs');
    expect(body).toContain('/models/rugby-sidam');
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
