/**
 * Shared helpers for autocomplete search behavior.
 *
 * createDebouncedSearch — debounced async search with stale-response handling.
 * formatCitationResult — format a citation source for display in search results.
 */

/**
 * Create a debounced search that discards stale responses.
 *
 * Empty queries fire immediately (to show default/all results).
 * Non-empty queries are debounced by `delay` ms.
 * If a newer search fires before an older one resolves, the older
 * result is silently discarded.
 */
export function createDebouncedSearch<T>(
  fetchFn: (query: string) => Promise<T>,
  onResults: (results: T) => void,
  delay: number = 200,
) {
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  return {
    search(query: string) {
      clearTimeout(timer);
      const gen = ++generation;
      const run = async () => {
        const results = await fetchFn(query);
        if (gen === generation) onResults(results);
      };
      if (query) {
        timer = setTimeout(run, delay);
      } else {
        run();
      }
    },
    cancel() {
      clearTimeout(timer);
      generation++;
    },
  };
}

/**
 * Format a citation source for display in autocomplete results.
 *
 * A child row leads with its parent, so an issue reads in context
 * ("Vol. 10 No. 6, March 1994 — GameRoom Magazine"); author/year follow.
 *
 * Examples:
 *   "The Encyclopedia of Pinball"
 *   "The Encyclopedia of Pinball — Richard Bueschel"
 *   "The Encyclopedia of Pinball — Richard Bueschel, 1996"
 *   "September 29, 1945 — Billboard, 1945"
 */
export function formatCitationResult(source: {
  name: string;
  author: string;
  year?: number | null;
  parent_name?: string | null;
}): string {
  const detail: string[] = [];
  if (source.parent_name) detail.push(source.parent_name);
  if (source.author) detail.push(source.author);
  if (source.year != null) detail.push(String(source.year));
  if (detail.length === 0) return source.name;
  return `${source.name} \u2014 ${detail.join(', ')}`;
}
