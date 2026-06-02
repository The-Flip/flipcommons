import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { goto, invalidateAll, afterNavigateCb, authMock, pageState } = vi.hoisted(() => ({
  goto: vi.fn(),
  invalidateAll: vi.fn(),
  // Capture the afterNavigate callback so a test can fire a synthetic popstate.
  afterNavigateCb: { current: undefined as ((nav: { type: string }) => void) | undefined },
  authMock: { isAuthenticated: true, load: () => Promise.resolve() },
  // Mutable so a test can change the URL before invoking the popstate callback;
  // the shell seeds its filter state from `page.url` (unlike the row-list
  // controller, which seeds from a `q` prop).
  pageState: { url: new URL('http://localhost/manufacturers') },
}));
vi.mock('$app/navigation', () => ({
  goto,
  invalidateAll,
  afterNavigate: (cb: (nav: { type: string }) => void) => {
    afterNavigateCb.current = cb;
  },
}));
vi.mock('$app/state', () => ({ page: pageState }));
vi.mock('$lib/auth.svelte', () => ({ auth: authMock }));

import FacetedCatalogListingFixture from './FacetedCatalogListing.fixture.svelte';

const ITEMS = [
  { slug: 'williams', name: 'Williams' },
  { slug: 'stern', name: 'Stern' },
];

describe('FacetedCatalogListing', () => {
  beforeEach(() => {
    goto.mockClear();
    invalidateAll.mockClear();
    authMock.isAuthenticated = true;
    pageState.url = new URL('http://localhost/manufacturers');
  });

  it('renders the seeded SSR page 1 without re-fetching it', () => {
    const fetchPage = vi.fn();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 }, fetchPage },
    });

    expect(screen.getByText('Williams')).toBeInTheDocument();
    // The loader is seeded from `initial`, so page 1 is not fetched again.
    expect(fetchPage).not.toHaveBeenCalled();
  });

  it('shows the count line with the singular/plural label from ENTITY_META', () => {
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: [ITEMS[0]], count: 1 } },
    });
    expect(screen.getByText(/^1 manufacturer$/)).toBeInTheDocument();
  });

  it('debounces typing into a single goto carrying the canonical query', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.type(screen.getByRole('searchbox'), 'will');

    // One navigation per pause, not per keystroke; the target is the entity base
    // path with the engine-serialized query.
    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
    expect(goto.mock.calls[0][0]).toContain('q=will');
    expect(goto.mock.calls[0][0]).toContain('/manufacturers');
  });

  it('navigates when a sidebar filter changes', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.click(await screen.findByTestId('sb-set'));

    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
    expect(goto.mock.calls[0][0]).toContain('foo=bar');
  });

  it('seeds filters from the request URL', async () => {
    pageState.url = new URL('http://localhost/manufacturers?foo=seeded');
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });
    expect(await screen.findByTestId('sb-foo')).toHaveTextContent('seeded');
  });

  it('re-seeds filters from the URL on a popstate navigation', async () => {
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });
    expect(await screen.findByTestId('sb-foo')).toHaveTextContent('none');

    // Back/forward: the URL changed, then afterNavigate fires with a popstate.
    pageState.url = new URL('http://localhost/manufacturers?foo=back');
    afterNavigateCb.current?.({ type: 'popstate' });

    await waitFor(() => expect(screen.getByTestId('sb-foo')).toHaveTextContent('back'));
    // Re-seeding adopts the URL; it must NOT trigger an outbound navigation.
    expect(goto).not.toHaveBeenCalled();
  });

  it('renders the sidebar disabled while the facet stream is pending, enabled once it lands', async () => {
    let resolve: (v: { foo: { public_id: string; name: string; count: number }[] }) => void;
    const pending = new Promise<{ foo: { public_id: string; name: string; count: number }[] }>(
      (r) => (resolve = r),
    );
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 }, filterOptions: pending },
    });

    expect(await screen.findByTestId('sb-state')).toHaveTextContent('disabled');
    resolve!({ foo: [{ public_id: 'x', name: 'X', count: 1 }] });
    await waitFor(() => expect(screen.getByTestId('sb-state')).toHaveTextContent('enabled'));
  });

  it('shows an inline retry that re-invalidates when the facet stream errors', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      // The load resolves the streamed promise to `undefined` on error.
      props: { initial: { items: ITEMS, count: 2 }, filterOptions: Promise.resolve(undefined) },
    });

    const retry = await screen.findByRole('button', { name: /retry/i });
    await user.click(retry);
    expect(invalidateAll).toHaveBeenCalledTimes(1);
  });

  it('renders active chips from the resolved options', async () => {
    pageState.url = new URL('http://localhost/manufacturers?foo=bar');
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });
    expect(await screen.findByText('Foo: bar')).toBeInTheDocument();
  });

  it('shows the create prompt only when the query-only count is zero and the user is authed', async () => {
    render(FacetedCatalogListingFixture, {
      props: {
        initial: { items: [], count: 0 },
        query: { q: 'nonesuch' },
        queryCount: Promise.resolve(0),
      },
    });

    expect(await screen.findByText(/does not exist/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /create/i })).toHaveAttribute(
      'href',
      '/manufacturers/new?name=nonesuch',
    );
  });

  it('does not show the create prompt when the query-only count is non-zero', async () => {
    // A non-zero query count means the name is taken — even with zero cards
    // showing (a facet is hiding the match), so no "create" offer.
    const queryCount = Promise.resolve(3);
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: [], count: 0 }, query: { q: 'williams' }, queryCount },
    });
    // Deterministically flush the `{#await}`: the count resolves, then a tick
    // lets the then-branch render. Absence now distinguishes "suppressed" from
    // "still pending".
    await queryCount;
    await Promise.resolve();
    expect(screen.queryByText(/does not exist/i)).not.toBeInTheDocument();
  });

  it('does not show the create prompt when unauthenticated', async () => {
    authMock.isAuthenticated = false;
    const queryCount = Promise.resolve(0);
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: [], count: 0 }, query: { q: 'nonesuch' }, queryCount },
    });
    await queryCount;
    await Promise.resolve();
    expect(screen.queryByText(/does not exist/i)).not.toBeInTheDocument();
  });
});
