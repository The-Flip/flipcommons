import { describe, expect, it, vi } from 'vitest';
import { createPaginatedLoader } from './paginated-loader.svelte';

/**
 * The `initial` seed is what lets the SSR /titles grid render page 1 from the
 * server response and continue infinite scroll at page 2. The regression these
 * tests guard is a seeded loader re-fetching page 1 (the double-fetch the SSR
 * plan warned about), or starting load-more at the wrong page.
 */
describe('createPaginatedLoader — seeded with initial', () => {
  it('uses the seed and does NOT fetch page 1', () => {
    const fetchPage = vi.fn();
    const loader = createPaginatedLoader(fetchPage, { items: [1, 2], count: 5 });

    expect(fetchPage).not.toHaveBeenCalled();
    expect(loader.loading).toBe(false);
    expect(loader.items).toEqual([1, 2]);
    expect(loader.count).toBe(5);
    expect(loader.hasMore).toBe(true);
  });

  it('load-more starts at page 2 and appends', async () => {
    const fetchPage = vi.fn().mockResolvedValue({ items: [3, 4], count: 5 });
    const loader = createPaginatedLoader(fetchPage, { items: [1, 2], count: 5 });

    loader.loadMore();
    // Page 1 came from the seed — the next fetch is page 2, not page 1.
    expect(fetchPage).toHaveBeenCalledExactlyOnceWith(2);

    await vi.waitFor(() => expect(loader.items).toEqual([1, 2, 3, 4]));
    expect(loader.count).toBe(5);
    expect(loader.hasMore).toBe(true); // 4 of 5 loaded — one more page to go
  });

  it('reports hasMore=false when the seed already holds every item', () => {
    const fetchPage = vi.fn();
    const loader = createPaginatedLoader(fetchPage, { items: [1, 2, 3], count: 3 });

    expect(loader.hasMore).toBe(false);
    loader.loadMore();
    expect(fetchPage).not.toHaveBeenCalled();
  });
});
