export type StreamStatus = 'loading' | 'ready' | 'error';

/**
 * Resolve a per-navigation streamed promise into sticky reactive state.
 *
 * `source` is read inside an `$effect`, so each time it returns a new promise (SvelteKit
 * re-runs `load` on a filter change, producing a fresh streamed promise) the resolution
 * re-runs. `value` is **sticky**: it holds the last successful result and is overwritten
 * only when a new promise resolves successfully, so a refetch shows the prior data instead
 * of blanking — the sidebar's stale-then-update behavior. A cancel guard drops out-of-order
 * resolutions so a slow earlier fetch can't clobber a faster later one.
 *
 * On SSR the effect never runs, so `value` stays `undefined` and `status` stays `'loading'`
 * — the disabled+empty shell renders server-side and hydrates when the stream lands.
 *
 * The caller's promise is expected to resolve to `undefined` on failure (e.g. the facet
 * load `.catch(() => undefined)`s); that maps to `status === 'error'`. The `.catch` here is
 * belt-and-suspenders for a promise that rejects instead.
 */
export function streamed<T>(source: () => Promise<T | undefined>) {
  let value = $state<T | undefined>(undefined);
  let status = $state<StreamStatus>('loading');

  $effect(() => {
    const promise = source();
    status = 'loading';
    let cancelled = false;
    promise
      .then((v) => {
        if (cancelled) return;
        if (v !== undefined) {
          value = v;
          status = 'ready';
        } else {
          status = 'error';
        }
      })
      .catch(() => {
        if (!cancelled) status = 'error';
      });
    return () => {
      cancelled = true;
    };
  });

  return {
    get value() {
      return value;
    },
    get status() {
      return status;
    },
  };
}
