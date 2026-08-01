import { onMount } from 'svelte';

/**
 * Unwrap a paginated list response for a `createPaginatedLoader` fetcher,
 * throwing on an error response (`data` undefined) instead of degrading to an
 * empty page.
 *
 * Degrading to `{ items: [], count: 0 }` is a trap: the loader reads it as a
 * real empty page, sets `hasMore` false and **silently, permanently halts
 * infinite scroll** on a single transient page-N failure (and an unseeded
 * loader's page-1 failure renders an empty list with no error). Throwing routes
 * the failure to the loader's `catch`, which records the error and leaves
 * `hasMore`/`nextPage` intact so the next sentinel hit retries the same page.
 * Safe because a 2xx always carries a real `{ items, count }` body — `data` is
 * undefined only on an actual error.
 */
export function unwrapPage<T>(data: { items: T[]; count: number } | undefined): {
  items: T[];
  count: number;
} {
  if (!data) throw new Error('Failed to load page');
  return data;
}

/**
 * Reactive paginated data loader for use inside Svelte components.
 *
 * Fetches the first page in `onMount` and exposes a `loadMore()` method
 * to fetch subsequent pages, appending results to the accumulated `items`.
 *
 * Pass `initial` to seed page 1 from an SSR load: `items`/`count` are
 * populated synchronously (so they render during SSR) and the `onMount`
 * first fetch is skipped — the next fetch is page 2. Used by the SSR
 * `/games` grid, whose page 1 already arrives in the server response.
 */
export function createPaginatedLoader<T>(
  fetchPage: (page: number) => Promise<{ items: T[]; count: number }>,
  initial?: { items: T[]; count: number },
) {
  let items = $state<T[]>(initial?.items ?? []);
  let count = $state(initial?.count ?? 0);
  let loading = $state(initial == null);
  let loadingMore = $state(false);
  let error = $state<string | null>(null);
  let nextPage = $state(initial != null ? 2 : 1);
  let hasMore = $state(initial != null ? initial.items.length < initial.count : true);

  async function fetchNextPage() {
    try {
      const result = await fetchPage(nextPage);
      items = [...items, ...result.items];
      count = result.count;
      nextPage += 1;
      hasMore = items.length < result.count;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load data';
    }
  }

  onMount(async () => {
    // Seeded from SSR — page 1 is already present; don't refetch it.
    if (initial != null) return;
    await fetchNextPage();
    loading = false;
  });

  function loadMore() {
    if (loadingMore || !hasMore) return;
    loadingMore = true;
    fetchNextPage().finally(() => {
      loadingMore = false;
    });
  }

  return {
    get items() {
      return items;
    },
    get count() {
      return count;
    },
    get loading() {
      return loading;
    },
    get loadingMore() {
      return loadingMore;
    },
    get error() {
      return error;
    },
    get hasMore() {
      return hasMore;
    },
    loadMore,
  };
}
