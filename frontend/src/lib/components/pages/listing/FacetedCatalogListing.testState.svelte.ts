import { SvelteURL } from 'svelte/reactivity';

/**
 * Reactive `$app/state` stand-in for the FacetedCatalogListing DOM tests. The
 * shell derives its filter state from `page.url`, so the mock must be
 * `$state`-backed for a mid-test URL change (a simulated landing, popstate or
 * link navigation) to re-run the derivation — a plain object would leave the
 * rendered state frozen at first read.
 */
export const pageState = $state({ url: new SvelteURL('http://localhost/manufacturers') });

/** Reset between tests (vi.resetModules would lose the mock's identity). */
export function resetPageState(href = 'http://localhost/manufacturers'): void {
  pageState.url = new SvelteURL(href);
}
