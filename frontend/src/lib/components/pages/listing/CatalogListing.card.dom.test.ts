import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/auth.svelte', () => ({
  auth: { isAuthenticated: true, load: () => Promise.resolve() },
}));
// The adapter emits MetaTags + listing JSON-LD, which read `page.url`.
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/people') } }));

import CatalogListingCardFixture from './CatalogListing.card.fixture.svelte';

const PEOPLE = [
  { slug: 'pat-lawlor', name: 'Pat Lawlor', thumbnail_url: null, credit_count: 12 },
  { slug: 'steve-ritchie', name: 'Steve Ritchie', thumbnail_url: null, credit_count: 9 },
];

describe('CatalogListing — card layout', () => {
  it('renders the card grid (not the row list) and lets cards self-link', () => {
    render(CatalogListingCardFixture, {
      props: { initial: { items: PEOPLE, count: 2 }, q: '' },
    });

    // The distinguisher: card layout routes to ServerPaginatedGrid (a `<div>`),
    // so there is no `<ul class="item-list">` (role `list`) from the row layout —
    // and cards aren't wrapped in the row's `${basePath}/${slug}` anchor (which
    // would nest inside the card's own link).
    expect(screen.queryByRole('list')).toBeNull();
    const link = screen.getByRole('link', { name: /Pat Lawlor/ });
    expect(link).toHaveAttribute('href', '/people/pat-lawlor');
    expect(screen.getByText('12 credits')).toBeInTheDocument();
  });

  it('still drives the count-based empty/create gates regardless of layout', () => {
    render(CatalogListingCardFixture, {
      props: { initial: { items: [], count: 0 }, q: 'nobody', canCreate: true },
    });

    expect(screen.getByText(/does not exist/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /create/i })).toHaveAttribute(
      'href',
      '/people/new?name=nobody',
    );
  });
});
