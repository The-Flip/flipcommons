import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SearchResultsSchema } from '$lib/api/schema';

const { goto, navigating } = vi.hoisted(() => ({
  goto: vi.fn(),
  // Mutable so a test can simulate an in-flight navigation to /search. Read at
  // render time; reset before each test.
  navigating: { to: null as { route: { id: string | null } } | null },
}));
vi.mock('$app/navigation', () => ({ goto }));
// `navigating` drives the pending affordance; `page` is read by card/meta helpers.
vi.mock('$app/state', () => ({
  navigating,
  page: { url: new URL('http://localhost/search') },
}));

import Page from './+page.svelte';

beforeEach(() => {
  navigating.to = null;
});

function section<T>(items: T[], hasMore = false) {
  return { items, has_more: hasMore };
}

function results(overrides: Partial<SearchResultsSchema> = {}): SearchResultsSchema {
  return {
    games: section([
      {
        entity_type: 'title' as const,
        name: 'Medieval Madness',
        public_id: 'medieval-madness',
        year: 1997,
        manufacturer: { public_id: 'williams', name: 'Williams' },
        thumbnail_url: null,
      },
      {
        entity_type: 'model' as const,
        name: 'Medieval Madness (Remake)',
        public_id: 'medieval-madness-remake',
        year: 2015,
        manufacturer: { public_id: 'williams', name: 'Williams' },
        thumbnail_url: null,
      },
    ]),
    manufacturers: section([
      { name: 'Medieval Co', slug: 'medieval-co', model_count: 4, thumbnail_url: null },
    ]),
    people: section([
      {
        name: 'Medi Designer',
        slug: 'medi-designer',
        aliases: [],
        credit_count: 7,
        thumbnail_url: null,
      },
    ]),
    ...overrides,
  };
}

describe('/search page', () => {
  it('shows the "type at least 3 characters" hint below the threshold, no results', () => {
    render(Page, { props: { data: { q: 'me', results: null } } });
    expect(screen.getByText(/type at least 3 characters/i)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
  });

  it('renders the three sections in order: Games, Manufacturers, People', () => {
    render(Page, { props: { data: { q: 'medieval', results: results() } } });
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(['Games', 'Manufacturers', 'People']);
    expect(screen.getByText('Medieval Madness')).toBeInTheDocument();
    expect(screen.getByText('Medieval Co')).toBeInTheDocument();
    expect(screen.getByText('Medi Designer')).toBeInTheDocument();
  });

  it('links a Model row to its model page', () => {
    render(Page, { props: { data: { q: 'medieval', results: results() } } });
    const link = screen.getByRole('link', { name: /Medieval Madness \(Remake\)/ });
    expect(link).toHaveAttribute('href', '/models/medieval-madness-remake');
  });

  it('hides empty sections', () => {
    render(Page, {
      props: {
        data: {
          q: 'medieval',
          results: results({ manufacturers: section([]), people: section([]) }),
        },
      },
    });
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(['Games']);
  });

  it('renders a "See all" listing link when a section has_more', () => {
    render(Page, {
      props: {
        data: {
          q: 'medieval',
          results: results({
            games: section(results().games.items, true),
          }),
        },
      },
    });
    const link = screen.getByRole('link', { name: /see all games matching "medieval"/i });
    expect(link).toHaveAttribute('href', '/titles?q=medieval');
  });

  it('omits the "See all" link when a section is within the cap', () => {
    render(Page, { props: { data: { q: 'medieval', results: results() } } });
    expect(screen.queryByRole('link', { name: /see all/i })).not.toBeInTheDocument();
  });

  it('shows a single "No results" line when every section is empty', () => {
    render(Page, {
      props: {
        data: {
          q: 'zzz',
          results: results({
            games: section([]),
            manufacturers: section([]),
            people: section([]),
          }),
        },
      },
    });
    // The visible message (the status line carries the same text for AT).
    expect(
      screen.getByText('No results for "zzz"', { selector: '.no-results' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
  });

  it('debounces typing into one ?q= navigation', async () => {
    const user = userEvent.setup();
    render(Page, { props: { data: { q: '', results: null } } });

    await user.type(screen.getByRole('searchbox'), 'medieval');

    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
    expect(goto.mock.calls[0][0]).toBe('/search?q=medieval');
    expect(goto.mock.calls[0][1]).toMatchObject({ replaceState: true, keepFocus: true });
  });

  it('seeds the search box from the committed q', () => {
    render(Page, { props: { data: { q: 'medieval', results: results() } } });
    expect(screen.getByRole('searchbox')).toHaveValue('medieval');
  });

  it('shows a "Searching…" affordance for the first query, before any results exist', () => {
    // An in-flight load to /search with a >=3-char query and no results yet — the
    // first-query case the result-dim alone can't cover (nothing on screen to dim).
    navigating.to = { route: { id: '/search' } };
    render(Page, { props: { data: { q: 'medieval', results: null } } });
    expect(screen.getByText(/^searching/i)).toBeInTheDocument();
    expect(screen.queryByText(/type at least/i)).not.toBeInTheDocument();
  });

  it('does not show "Searching…" for a sub-threshold in-flight nav', () => {
    // Clearing back toward the hint navigates too, but skips the backend — no
    // "Searching…", just the hint.
    navigating.to = { route: { id: '/search' } };
    render(Page, { props: { data: { q: 'me', results: null } } });
    expect(screen.queryByText(/^searching/i)).not.toBeInTheDocument();
    expect(screen.getByText(/type at least 3 characters/i)).toBeInTheDocument();
  });

  it('announces the visible result count to assistive tech', () => {
    render(Page, { props: { data: { q: 'medieval', results: results() } } });
    const live = screen.getByText(/showing 4 results/i);
    // The polite live region wraps the announcement.
    expect(live.closest('[aria-live="polite"]')).not.toBeNull();
  });
});
