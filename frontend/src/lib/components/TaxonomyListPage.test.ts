import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';

// The page emits MetaTags + listing JSON-LD, which read `page.url`.
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/tags') } }));

import TaxonomyListPage from './TaxonomyListPage.svelte';
import ListSnippetFixture from './TaxonomyListPage.list-snippet.fixture.svelte';
import HeaderSnippetFixture from './TaxonomyListPage.header-snippet.fixture.svelte';

const ITEMS = [
  { slug: 'alpha', name: 'Alpha' },
  { slug: 'beta', name: 'Beta' },
];

describe('TaxonomyListPage', () => {
  it('renders title, subtitle, and the list body via listSnippet', () => {
    const { body } = render(ListSnippetFixture, {
      props: {
        catalogKey: 'tag',
        subtitle: 'All the tags.',
        items: ITEMS,
      },
    });

    expect(body).toContain('Tags');
    expect(body).toContain('All the tags.');
    expect(body).toContain('Alpha');
    expect(body).toContain('Beta');
    expect(body).toContain('/tags/alpha');
    expect(body).toContain('/tags/beta');
  });

  it('renders loading state', () => {
    const { body } = render(TaxonomyListPage, {
      props: {
        catalogKey: 'tag',
        items: [],
        loading: true,
      },
    });

    expect(body).toContain('Loading...');
    expect(body).not.toContain('item-list');
  });

  it('renders error state', () => {
    const { body } = render(TaxonomyListPage, {
      props: {
        catalogKey: 'tag',
        items: [],
        error: 'Something went wrong',
      },
    });

    expect(body).toContain('Failed to load tags.');
    expect(body).not.toContain('Alpha');
  });

  it('renders empty state', () => {
    const { body } = render(TaxonomyListPage, {
      props: {
        catalogKey: 'tag',
        items: [],
      },
    });

    expect(body).toContain('No tags found.');
  });

  // Inline style="…" attributes require `style-src-attr 'unsafe-hashes'`
  // (or 'unsafe-inline') under our CSP. A regression here — e.g. a new
  // prop that passes a style string through to .item-row — would only
  // surface as Sentry violation reports during the report-only window,
  // and would block the eventual flip to enforce. Catch it at unit time.
  it('does not emit inline style attributes on row links (CSP)', () => {
    const { body } = render(ListSnippetFixture, {
      props: {
        catalogKey: 'tag',
        items: ITEMS,
      },
    });

    expect(body).toMatch(/class="[^"]*\bitem-row\b[^"]*"/);
    expect(body).not.toMatch(/<a[^>]*\bitem-row\b[^>]*\sstyle=/);
  });

  it('includes page title in head', () => {
    const { head } = render(TaxonomyListPage, {
      props: {
        catalogKey: 'tag',
        items: [],
      },
    });

    expect(head).toContain('Tags');
  });

  it('renders custom header content via headerSnippet', () => {
    const { body } = render(HeaderSnippetFixture);

    expect(body).toContain('Rich introductory content here.');
    expect(body).not.toContain('subtitle');
  });

  it('omits search input below SEARCH_THRESHOLD', () => {
    // 2 items is far below the 12-item threshold.
    const { body } = render(TaxonomyListPage, {
      props: {
        catalogKey: 'tag',
        items: ITEMS,
        canCreate: true,
      },
    });

    expect(body).not.toContain('type="search"');
  });

  it('renders search input at/above SEARCH_THRESHOLD', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      slug: `t-${i}`,
      name: `Tag ${i}`,
    }));
    const { body } = render(TaxonomyListPage, {
      props: {
        catalogKey: 'tag',
        items: many,
        canCreate: true,
      },
    });

    expect(body).toContain('type="search"');
  });
});
