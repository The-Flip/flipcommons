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

// The adapter emits MetaTags + listing JSON-LD, which read `page.url`.
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/franchises') } }));

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

  // The box holds a draft that a landing navigation must not rewind. The commit
  // is a `goto` whose server load reseeds `q` a round-trip later — by which time
  // a still-typing user is ahead of the committed value.
  describe('search box', () => {
    const props = (q: string) => ({ initial: { items: ROWS, count: 12 }, q });

    it('keeps a draft typed ahead of a landing navigation', async () => {
      const user = userEvent.setup();
      const { rerender } = render(CatalogListingFixture, { props: props('') });
      const box = screen.getByRole('searchbox');

      // Type, pause: the debounce commits `?q=star` and the navigation starts.
      await user.type(box, 'star');
      await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
      expect(goto.mock.calls[0][0]).toContain('q=star');

      // The user types on while that navigation is still in flight, then it
      // lands and the server load reseeds the committed `q`.
      await user.type(box, 'fi');
      await rerender(props('star'));

      expect(box).toHaveValue('starfi');
    });

    // Back/forward outranks an uncommitted draft — the `searchDraft` contract.
    it('lets back/forward override a draft whose commit is still pending', async () => {
      const user = userEvent.setup();
      const { rerender } = render(CatalogListingFixture, { props: props('star') });
      const box = screen.getByRole('searchbox');

      await user.type(box, 'fi');
      expect(box).toHaveValue('starfi');

      await rerender(props('addams'));
      expect(box).toHaveValue('addams');

      await new Promise((resolve) => setTimeout(resolve, 400));
      expect(box).toHaveValue('addams');
      expect(goto).not.toHaveBeenCalled();
    });

    it('adopts a committed q that changes with nothing pending', async () => {
      const { rerender } = render(CatalogListingFixture, { props: props('star') });
      expect(screen.getByRole('searchbox')).toHaveValue('star');

      // Back/forward: the committed value changes from outside the box, and
      // the user has no draft in flight — the box follows the URL.
      await rerender(props('addams'));

      expect(screen.getByRole('searchbox')).toHaveValue('addams');
    });
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
