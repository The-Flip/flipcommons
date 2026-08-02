import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetPageState } from './FacetedCatalogListing.testState.svelte';

const { goto, gotoCalls, invalidateAll, authMock } = vi.hoisted(() => {
  // Each goto returns a promise the test settles by hand: `land()` adopts the
  // target into the page URL then resolves (a navigation that landed), a bare
  // `resolve()` without a URL change is a navigation that settled without
  // landing (blocked, or aborted by an invalidation).
  const gotoCalls: { href: string; resolve: () => void }[] = [];
  const goto = vi.fn(
    (href: string) => new Promise<void>((resolve) => gotoCalls.push({ href, resolve })),
  );
  return {
    goto,
    gotoCalls,
    invalidateAll: vi.fn(),
    authMock: { isAuthenticated: true, load: () => Promise.resolve() },
  };
});
vi.mock('$app/navigation', () => ({ goto, invalidateAll }));
vi.mock('$app/state', async () => {
  const { pageState } = await import('./FacetedCatalogListing.testState.svelte');
  return { page: pageState };
});
vi.mock('$lib/auth.svelte', () => ({ auth: authMock }));

import FacetedCatalogListingFixture from './FacetedCatalogListing.fixture.svelte';

const ITEMS = [
  { slug: 'williams', name: 'Williams' },
  { slug: 'stern', name: 'Stern' },
];

/** Land a goto: the URL updates to its target, then its promise settles. */
async function land(call: { href: string; resolve: () => void }) {
  resetPageState(new URL(call.href, 'http://localhost').href);
  call.resolve();
  // Let the settlement's `.finally` clear the pending intent.
  await new Promise<void>((r) => setTimeout(r, 0));
}

describe('FacetedCatalogListing', () => {
  beforeEach(() => {
    goto.mockClear();
    gotoCalls.length = 0;
    invalidateAll.mockClear();
    authMock.isAuthenticated = true;
    resetPageState();
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

  it('keeps the draft in the box when its own commit lands', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.type(screen.getByRole('searchbox'), 'will');
    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));

    await land(gotoCalls[0]);

    expect(screen.getByRole('searchbox')).toHaveValue('will');
    expect(goto).toHaveBeenCalledTimes(1);
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
    resetPageState('http://localhost/manufacturers?foo=seeded');
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });
    expect(await screen.findByTestId('sb-foo')).toHaveTextContent('seeded');
  });

  it('adopts the URL on a popstate navigation', async () => {
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });
    expect(await screen.findByTestId('sb-foo')).toHaveTextContent('none');

    // Back/forward: the framework updates `page.url`; the derivation re-runs.
    resetPageState('http://localhost/manufacturers?foo=back');

    await waitFor(() => expect(screen.getByTestId('sb-foo')).toHaveTextContent('back'));
    // Adopting the URL must NOT trigger an outbound navigation.
    expect(goto).not.toHaveBeenCalled();
  });

  it('adopts the URL when a link navigation lands on a different URL', async () => {
    // Top-nav "Games"/"Manufacturers" while filtered: SvelteKit keeps the
    // component instance (same route id), so only the URL changes.
    resetPageState('http://localhost/manufacturers?foo=bar');
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });
    expect(await screen.findByTestId('sb-foo')).toHaveTextContent('bar');
    expect(await screen.findByText('Foo: bar')).toBeInTheDocument();

    resetPageState('http://localhost/manufacturers');

    await waitFor(() => expect(screen.getByTestId('sb-foo')).toHaveTextContent('none'));
    expect(screen.queryByText('Foo: bar')).not.toBeInTheDocument();
    // Adopting the URL must not bounce a navigation back out.
    expect(goto).not.toHaveBeenCalled();
  });

  it('replaces the search draft when the committed query arrives from outside', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    // Mid-draft (nothing committed yet), a back/forward landing carries a new q.
    await user.type(screen.getByRole('searchbox'), 'wi');
    resetPageState('http://localhost/manufacturers?q=back');

    await waitFor(() => expect(screen.getByRole('searchbox')).toHaveValue('back'));
    // The replaced draft's scheduled commit is abandoned: no navigation fires.
    await new Promise<void>((r) => setTimeout(r, 400));
    expect(goto).not.toHaveBeenCalled();
  });

  it('renders the requested state while its navigation is in flight', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.click(await screen.findByTestId('sb-set'));

    // Before the landing: the sidebar and chips already show the intent.
    await waitFor(() => expect(screen.getByTestId('sb-foo')).toHaveTextContent('bar'));
    expect(screen.getByText('Foo: bar')).toBeInTheDocument();

    await land(gotoCalls[0]);
    expect(screen.getByTestId('sb-foo')).toHaveTextContent('bar');
    expect(goto).toHaveBeenCalledTimes(1);
  });

  it('composes a second intent on the pending target of the first', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.click(await screen.findByTestId('sb-set'));
    await user.click(await screen.findByTestId('sb-set-bar'));

    await waitFor(() => expect(goto).toHaveBeenCalledTimes(2));
    // The second target carries BOTH fields — composed on the first intent's
    // requested state, not on the stale committed URL.
    expect(goto.mock.calls[1][0]).toContain('foo=bar');
    expect(goto.mock.calls[1][0]).toContain('bar=baz');
  });

  it('keeps the newer intent pending when a superseded goto settles', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.click(await screen.findByTestId('sb-set'));
    await user.click(await screen.findByTestId('sb-set-bar'));
    await waitFor(() => expect(goto).toHaveBeenCalledTimes(2));

    // The superseded first goto settles without landing (SvelteKit aborts it).
    gotoCalls[0].resolve();
    await new Promise<void>((r) => setTimeout(r, 0));
    expect(screen.getByTestId('sb-foo')).toHaveTextContent('bar');
    expect(screen.getByTestId('sb-bar')).toHaveTextContent('baz');

    await land(gotoCalls[1]);
    expect(screen.getByTestId('sb-foo')).toHaveTextContent('bar');
    expect(screen.getByTestId('sb-bar')).toHaveTextContent('baz');
  });

  it('snaps back to the committed URL when a navigation settles without landing', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.click(await screen.findByTestId('sb-set'));
    await waitFor(() => expect(screen.getByTestId('sb-foo')).toHaveTextContent('bar'));

    // Settle without a URL change: blocked, or aborted by an invalidation.
    gotoCalls[0].resolve();

    await waitFor(() => expect(screen.getByTestId('sb-foo')).toHaveTextContent('none'));
  });

  it('commits a mid-debounce draft on top of an externally landed filter', async () => {
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    // Draft typed but not yet committed when a navigation lands a filter change
    // that leaves q untouched (e.g. another surface navigated).
    await user.type(screen.getByRole('searchbox'), 'wi');
    resetPageState('http://localhost/manufacturers?foo=bar');

    // The draft survives (its committed value didn't change) and its commit
    // composes on the landed state.
    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
    expect(goto.mock.calls[0][0]).toContain('foo=bar');
    expect(goto.mock.calls[0][0]).toContain('q=wi');
  });

  it('removes a chip through a single navigation clearing that field', async () => {
    resetPageState('http://localhost/manufacturers?foo=bar&q=will');
    const user = userEvent.setup();
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });

    await user.click(await screen.findByRole('button', { name: /remove filter/i }));

    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
    expect(goto.mock.calls[0][0]).not.toContain('foo=');
    expect(goto.mock.calls[0][0]).toContain('q=will');
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
    resetPageState('http://localhost/manufacturers?foo=bar');
    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 } },
    });
    expect(await screen.findByText('Foo: bar')).toBeInTheDocument();
  });

  it('renders active chips while the facet stream is pending, and when it has failed', async () => {
    // The chip row is the only removal affordance for chip-only dimensions, so
    // it must not wait for (or lose) the streamed facet payload.
    resetPageState('http://localhost/manufacturers?foo=bar');
    const { unmount } = render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 }, filterOptions: new Promise<never>(() => {}) },
    });
    expect(await screen.findByText('Foo: bar')).toBeInTheDocument();
    unmount();

    render(FacetedCatalogListingFixture, {
      props: { initial: { items: ITEMS, count: 2 }, filterOptions: Promise.resolve(undefined) },
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

  // Title is the one entity whose listing (/games, via the listingPath
  // override) and create route (/titles/new) live under different segments.
  // Regression pins for the fix where filter navigation targeted the entity
  // plural and bounced every filter change through the /titles 301 as a full
  // document load.
  describe('catalogKey="title" (the games listing)', () => {
    it('filter navigation targets /games, not the entity plural', async () => {
      resetPageState('http://localhost/games');
      const user = userEvent.setup();
      render(FacetedCatalogListingFixture, {
        props: { catalogKey: 'title' as const, initial: { items: ITEMS, count: 2 } },
      });

      await user.click(await screen.findByTestId('sb-set'));

      await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
      expect(goto.mock.calls[0][0]).toMatch(/^\/games\?/);
    });

    it('the create prompt still targets /titles/new', async () => {
      resetPageState('http://localhost/games?q=nonesuch');
      render(FacetedCatalogListingFixture, {
        props: {
          catalogKey: 'title' as const,
          initial: { items: [], count: 0 },
          query: { q: 'nonesuch' },
          queryCount: Promise.resolve(0),
        },
      });

      expect(await screen.findByRole('link', { name: /create/i })).toHaveAttribute(
        'href',
        '/titles/new?name=nonesuch',
      );
    });
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
