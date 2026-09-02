import { render } from 'svelte/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { pageState, authState } = vi.hoisted(() => ({
  pageState: {
    params: { slug: 'williams' },
    url: new URL('http://localhost:5173/manufacturers/williams'),
    route: { id: '/manufacturers/[slug]' },
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
import { MOCK_MANUFACTURER } from './manufacturer.fixtures';

describe('manufacturer layout', () => {
  beforeEach(() => {
    pageState.params.slug = 'williams';
    pageState.url = new URL('http://localhost:5173/manufacturers/williams');
    pageState.route.id = '/manufacturers/[slug]';
    authState.isAuthenticated = false;
  });

  it('renders the action bar without the legacy tab navigation on the detail route', () => {
    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, q: '', jsonLd: {} } },
    });

    expect(body).toContain('History');
    expect(body).not.toContain('>Back<');
    expect(body).not.toContain('Page sections');
  });

  it('strips the detail shell on sources subroutes (focus mode)', () => {
    pageState.url = new URL('http://localhost:5173/manufacturers/williams/sources');
    pageState.route.id = '/manufacturers/[slug]/sources';

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, q: '', jsonLd: {} } },
    });

    expect(body).toContain('Child content');
    expect(body).not.toContain('History');
    expect(body).not.toContain('Page sections');
  });

  it('strips the detail shell on edit-history subroutes (focus mode)', () => {
    pageState.url = new URL('http://localhost:5173/manufacturers/williams/edit-history');
    pageState.route.id = '/manufacturers/[slug]/edit-history';

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, q: '', jsonLd: {} } },
    });

    expect(body).toContain('Child content');
    expect(body).not.toContain('History');
  });

  it('renders a direct edit link on the Links sidebar section when authenticated', () => {
    authState.isAuthenticated = true;

    const { body } = render(Harness, {
      props: { data: { profile: MOCK_MANUFACTURER, q: '', jsonLd: {} } },
    });

    expect(body).toContain('Links');
    expect(body).toContain('>edit<');
  });
});
