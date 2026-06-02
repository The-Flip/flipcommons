import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { goto, authMock } = vi.hoisted(() => ({
  goto: vi.fn(),
  authMock: { isAuthenticated: true, load: () => Promise.resolve() },
}));
vi.mock('$app/navigation', () => ({ goto }));

// `load()` is a no-op so the component's auth.load() $effect doesn't hit fetch
// in jsdom; `isAuthenticated` defaults true (the create-prompt / "+ New" gates)
// and is toggled per test for the unauthenticated case.
vi.mock('$lib/auth.svelte', () => ({ auth: authMock }));

import CatalogListingFixture from './CatalogListing.fixture.svelte';

// Twelve+ rows so the search box renders (SEARCH_THRESHOLD === 12).
const ROWS = [
  { slug: 'star-wars', name: 'Star Wars', title_count: 4 },
  { slug: 'addams-family', name: 'Addams Family', title_count: 2 },
  ...Array.from({ length: 10 }, (_, i) => ({
    slug: `franchise-${i}`,
    name: `Franchise ${i}`,
    title_count: i,
  })),
];

describe('CatalogListing', () => {
  beforeEach(() => {
    goto.mockClear();
    authMock.isAuthenticated = true;
  });

  it('renders the seeded SSR page 1 without re-fetching it', () => {
    const fetchPage = vi.fn();
    render(CatalogListingFixture, {
      props: { initial: { items: ROWS, count: 12 }, q: '', fetchPage },
    });

    expect(screen.getByText('Star Wars')).toBeInTheDocument();
    // The loader is seeded from `initial`, so page 1 is not fetched again.
    expect(fetchPage).not.toHaveBeenCalled();
  });

  it('links each row to its detail page under the entity base path', () => {
    render(CatalogListingFixture, {
      props: { initial: { items: ROWS, count: 12 }, q: '' },
    });
    expect(screen.getByRole('link', { name: /Star Wars/ })).toHaveAttribute(
      'href',
      '/franchises/star-wars',
    );
  });

  it('debounces typing into a single goto ?q=', async () => {
    const user = userEvent.setup();
    render(CatalogListingFixture, {
      props: { initial: { items: ROWS, count: 12 }, q: '' },
    });

    await user.type(screen.getByRole('searchbox'), 'star');

    // One navigation per pause, not per keystroke.
    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
    expect(goto.mock.calls[0][0]).toContain('q=star');
  });

  it('shows the create prompt when a search yields zero and the user can create', () => {
    render(CatalogListingFixture, {
      props: { initial: { items: [], count: 0 }, q: 'nonesuch', canCreate: true },
    });

    expect(screen.getByText(/does not exist/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /create/i })).toHaveAttribute(
      'href',
      '/franchises/new?name=nonesuch',
    );
  });

  it('shows an empty state (not a create prompt) for an unfiltered empty list', () => {
    render(CatalogListingFixture, {
      props: { initial: { items: [], count: 0 }, q: '', canCreate: true },
    });

    expect(screen.getByText(/no franchises found/i)).toBeInTheDocument();
    expect(screen.queryByText(/does not exist/i)).not.toBeInTheDocument();
  });

  // Below SEARCH_THRESHOLD there's no search box, so creation is offered via a
  // header "+ New X" menu instead — auth-gated, and suppressed while a search is
  // active so a `?q=` URL on a small entity never surfaces both affordances.
  it('shows the "+ New X" action menu below the threshold when authed and unfiltered', async () => {
    const user = userEvent.setup();
    render(CatalogListingFixture, {
      props: { initial: { items: ROWS.slice(0, 3), count: 3 }, q: '', canCreate: true },
    });

    expect(screen.queryByRole('searchbox')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getByRole('menuitem', { name: /\+ New Franchise/ })).toBeInTheDocument();
  });

  it('hides the action menu while a search is active (no double create affordance)', () => {
    render(CatalogListingFixture, {
      props: { initial: { items: ROWS.slice(0, 3), count: 3 }, q: 'star', canCreate: true },
    });

    // A query is active, so the search box is the create surface; the header
    // menu must not also appear.
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
  });

  it('hides the action-menu trigger entirely when unauthenticated', () => {
    authMock.isAuthenticated = false;
    render(CatalogListingFixture, {
      props: { initial: { items: ROWS.slice(0, 3), count: 3 }, q: '', canCreate: true },
    });

    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
  });
});
