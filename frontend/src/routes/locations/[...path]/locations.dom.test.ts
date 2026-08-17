import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { authMock, pageState } = vi.hoisted(() => ({
  authMock: { isAuthenticated: true, load: () => Promise.resolve() },
  pageState: { url: new URL('http://localhost/locations') },
}));

vi.mock('$app/navigation', () => ({ goto: vi.fn(), invalidateAll: vi.fn() }));
vi.mock('$app/paths', () => ({ resolve: (p: string) => p, asset: (p: string) => p }));
vi.mock('$app/state', () => ({
  page: {
    params: {},
    get url() {
      return pageState.url;
    },
  },
}));
vi.mock('$lib/auth.svelte', () => ({ auth: authMock }));

import Layout from './+layout.svelte';
import SubrouteHarness from './location-subroute.test-harness.svelte';

type Manufacturer = {
  name: string;
  slug: string;
  model_count: number;
  thumbnail_url: string | null;
};

type ChildRef = {
  name: string;
  public_id: string;
  location_type: string;
  manufacturer_count: number;
};

type AncestorRef = { name: string; public_id: string };

type Profile = {
  name: string;
  slug: string;
  public_id: string;
  location_type: string | null;
  description: { text: string; html: string; plain: string };
  manufacturer_count: number;
  ancestors: AncestorRef[];
  children: ChildRef[];
  manufacturers: Manufacturer[];
};

const EMPTY_DESCRIPTION = { text: '', html: '', plain: '' };

function renderLayout(profile: Profile) {
  render(Layout, {
    data: { profile },
    children: () => ({}) as never,
  } as unknown as Parameters<typeof render>[1]);
}

const ROOT: Profile = {
  name: '',
  slug: '',
  public_id: '',
  location_type: null,
  description: EMPTY_DESCRIPTION,
  manufacturer_count: 4,
  ancestors: [],
  children: [
    {
      name: 'United States',
      public_id: 'usa',
      location_type: 'country',
      manufacturer_count: 3,
    },
    {
      name: 'Netherlands',
      public_id: 'netherlands',
      location_type: 'country',
      manufacturer_count: 1,
    },
  ],
  manufacturers: [],
};

const COUNTRY: Profile = {
  name: 'United States',
  slug: 'usa',
  public_id: 'usa',
  location_type: 'country',
  description: EMPTY_DESCRIPTION,
  manufacturer_count: 3,
  ancestors: [],
  children: [
    {
      name: 'Illinois',
      public_id: 'usa/il',
      location_type: 'state',
      manufacturer_count: 3,
    },
  ],
  manufacturers: [],
};

const CITY: Profile = {
  name: 'Chicago',
  slug: 'chicago',
  public_id: 'usa/il/chicago',
  location_type: 'city',
  description: EMPTY_DESCRIPTION,
  manufacturer_count: 2,
  ancestors: [
    { name: 'United States', public_id: 'usa' },
    { name: 'Illinois', public_id: 'usa/il' },
  ],
  children: [],
  manufacturers: [],
};

describe('locations layout — root', () => {
  beforeEach(() => {
    authMock.isAuthenticated = true;
  });

  it('shows "Locations" heading and Countries sidebar', () => {
    renderLayout(ROOT);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Locations');
    expect(screen.getByText('Countries')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'United States' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Netherlands' })).toBeInTheDocument();
  });

  it('authenticated users see "+ New Country" in the edit menu', async () => {
    const user = userEvent.setup();
    renderLayout(ROOT);
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    const item = screen.getByRole('menuitem', { name: '+ New Country' });
    expect(item).toHaveAttribute('href', '/locations/new');
  });

  it('does not render History or Sources at root', () => {
    renderLayout(ROOT);
    expect(screen.queryByRole('link', { name: 'History' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Tools' })).toBeNull();
  });

  it('unauthenticated users get no edit menu at root', () => {
    authMock.isAuthenticated = false;
    renderLayout(ROOT);
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
  });
});

describe('locations layout — country', () => {
  beforeEach(() => {
    authMock.isAuthenticated = true;
  });

  it('renders the breadcrumb back to /locations', () => {
    renderLayout(COUNTRY);
    const nav = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(nav).toHaveTextContent('Locations');
    expect(screen.getByRole('link', { name: 'Locations' })).toHaveAttribute('href', '/locations');
  });

  it('sidebar heading is "States" when all children are states', () => {
    renderLayout(COUNTRY);
    expect(screen.getByText('States')).toBeInTheDocument();
  });

  it('edit menu has Description / Basics / Divisions / Aliases / + New State / Delete on a country', async () => {
    const user = userEvent.setup();
    renderLayout(COUNTRY);
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    // Name / parent / slug / location_type are intentionally absent because
    // they define the location's canonical path and hierarchy.
    expect(screen.queryByRole('menuitem', { name: 'Name' })).toBeNull();
    expect(screen.queryByRole('menuitem', { name: 'Parent' })).toBeNull();
    expect(screen.getByRole('menuitem', { name: 'Description' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Basics' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Divisions' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Aliases' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '+ New State' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Delete United States' })).toBeInTheDocument();
  });

  it('History and Sources visible at depth ≥ 1', () => {
    renderLayout(COUNTRY);
    expect(screen.getByRole('link', { name: 'History' })).toHaveAttribute(
      'href',
      '/locations/usa/edit-history',
    );
  });
});

describe('locations layout — meta tags', () => {
  const defaultUrl = pageState.url;

  afterEach(() => {
    pageState.url = defaultUrl;
  });

  it('emits canonical, description, and og tags for a location page', () => {
    pageState.url = new URL('http://localhost/locations/usa/il/chicago');
    renderLayout(CITY);
    expect(document.title).toBe('Chicago — Flipcommons Pinball Encyclopedia');
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'http://localhost/locations/usa/il/chicago',
    );
    // No entity description on the fixture, so the geographic fallback —
    // ancestors nearest-first — keeps sibling pages' descriptions distinct.
    expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute(
      'content',
      'Pinball manufacturers in Chicago, Illinois, United States.',
    );
    expect(document.head.querySelector('meta[property="og:type"]')).toHaveAttribute(
      'content',
      'article',
    );
  });

  it('prefers the entity description over the geographic fallback', () => {
    pageState.url = new URL('http://localhost/locations/usa/il/chicago');
    renderLayout({
      ...CITY,
      description: {
        text: 'Home of pinball.',
        html: '<p>Home of pinball.</p>',
        plain: 'Home of pinball.',
      },
    });
    expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute(
      'content',
      'Home of pinball.',
    );
  });

  it('emits listing-flavored tags at the global root', () => {
    renderLayout(ROOT);
    expect(document.title).toBe('Locations — Flipcommons Pinball Encyclopedia');
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'http://localhost/locations',
    );
    expect(document.head.querySelector('meta[property="og:type"]')).toHaveAttribute(
      'content',
      'website',
    );
    expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute(
      'content',
      'Browse pinball manufacturers by country, region, and city.',
    );
  });
});

describe('locations layout — entity context for sub-routes', () => {
  it('publishes the location name and detail href to a sub-route page', () => {
    render(SubrouteHarness, {
      data: { profile: COUNTRY },
      pageData: { changesets: [] },
    } as unknown as Parameters<typeof render>[1]);

    // EditHistory reads both from the entity context; without it the whole
    // sub-route 500s on the server before any of this renders.
    expect(screen.getByRole('heading', { name: 'Edit History' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/locations/usa');
    expect(screen.getByRole('link', { name: 'United States' })).toHaveAttribute(
      'href',
      '/locations/usa',
    );
  });
});

describe('locations layout — city (no expected child)', () => {
  beforeEach(() => {
    authMock.isAuthenticated = true;
  });

  it('omits the "+ New …" item when the location has no expected child', async () => {
    const user = userEvent.setup();
    renderLayout(CITY);
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    // The other edit sections still appear; only the conditional "+ New …"
    // item is suppressed.
    expect(screen.getByRole('menuitem', { name: 'Description' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Divisions' })).toBeNull();
    expect(screen.queryByRole('menuitem', { name: /\+ New/ })).toBeNull();
  });
});
