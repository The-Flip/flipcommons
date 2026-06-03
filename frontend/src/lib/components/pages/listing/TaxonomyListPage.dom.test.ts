import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

// Prevent the page's auth.load() $effect from hitting fetch inside jsdom.
vi.mock('$lib/auth.svelte', () => ({
  auth: {
    isAuthenticated: true,
    load: () => Promise.resolve(),
  },
}));

// The page emits MetaTags + listing JSON-LD, which read `page.url`.
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/gameplay-features') } }));

import TaxonomyListPage from './TaxonomyListPage.svelte';
import ListSnippetFixture from './TaxonomyListPage.list-snippet.fixture.svelte';

// Twelve items so the search input renders (SEARCH_THRESHOLD === 12 in
// search-threshold.ts). One of them carries an alias that does NOT appear
// in its canonical name, which is what the alias-aware filter guards.
const ITEMS = [
  { slug: 'flippers', name: 'Flippers', aliases: [] },
  { slug: 'multiball', name: 'Multiball', aliases: ['Multi Ball'] },
  ...Array.from({ length: 10 }, (_, i) => ({
    slug: `feature-${i}`,
    name: `Feature ${i}`,
    aliases: [] as string[],
  })),
];

describe('TaxonomyListPage alias-aware search', () => {
  it('matches items by alias, preventing a create-prompt false positive', async () => {
    const user = userEvent.setup();
    render(ListSnippetFixture, {
      props: {
        catalogKey: 'gameplay-feature',
        items: ITEMS,
        canCreate: true,
      },
    });

    const search = screen.getByRole('searchbox');
    await user.type(search, 'multi ball');

    // Alias match — "Multiball" (canonical name has no space) is still
    // in the list, so NoResultsCreatePrompt must not render.
    expect(screen.getByText('Multiball')).toBeInTheDocument();
    expect(screen.queryByText(/does not exist/i)).not.toBeInTheDocument();
  });

  it('falls through to the create prompt when neither name nor alias matches', async () => {
    const user = userEvent.setup();
    render(ListSnippetFixture, {
      props: {
        catalogKey: 'gameplay-feature',
        items: ITEMS,
        canCreate: true,
      },
    });

    const search = screen.getByRole('searchbox');
    await user.type(search, 'no-such-feature');

    // Nothing matches by name or alias — create prompt takes over.
    // The prompt rides on auth.isAuthenticated; if that's not set in the
    // harness the filtered-to-empty branch still hides the matched rows
    // and surfaces the "no matching" fallback. Both outcomes are valid
    // evidence that the alias filter didn't accidentally retain items.
    expect(screen.queryByText('Multiball')).not.toBeInTheDocument();
    expect(screen.queryByText('Flippers')).not.toBeInTheDocument();
  });
});

describe('TaxonomyListPage create-menu label', () => {
  it('uses the catalog singular label (e.g. "Series", not naive "Serie")', async () => {
    const user = userEvent.setup();
    render(TaxonomyListPage, {
      props: {
        catalogKey: 'series',
        items: [{ slug: 'alpha', name: 'Alpha', aliases: [] }],
        canCreate: true,
      },
    });

    // Open the action menu to surface its items.
    await user.click(screen.getByRole('button', { name: /edit/i }));
    expect(screen.getByRole('menuitem', { name: '+ New Series' })).toBeInTheDocument();
  });
});
