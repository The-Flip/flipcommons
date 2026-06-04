<script lang="ts">
  import { goto } from '$app/navigation';
  import { navigating } from '$app/state';
  import { resolve } from '$app/paths';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import SearchResults from './_components/SearchResults.svelte';
  import { MIN_SEARCH_QUERY_LENGTH, pageTitle } from '$lib/constants';

  let { data } = $props();

  // Writable `$derived`: re-adopts `data.q` whenever the load re-runs (a debounce
  // landing, back/forward), but stays locally writable so it can bind the input.
  let queryInput = $derived(data.q);

  // Debounce typing → one `goto ?q=` per pause, which re-runs the SSR load.
  // `replaceState` so typing a multi-character query leaves a single history
  // entry, not one per keystroke-pause. Skipped when the input already matches
  // the committed `q` (seed / popstate / our own goto's landing, each of which
  // resets `queryInput` via the `$derived` above) so there's no echo loop.
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const next = queryInput.trim();
    if (next === data.q) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      const search = next ? `?q=${encodeURIComponent(next)}` : '';
      void goto(`${resolve('/search')}${search}`, {
        keepFocus: true,
        replaceState: true,
        noScroll: true,
      });
    }, 250);
    return () => clearTimeout(timer);
  });

  // A real (≥ MIN) query whose SSR load is in flight. Keyed off `queryInput` (the
  // live input), so it's true the moment the debounced `goto` starts — covering the
  // FIRST query (no prior results to dim yet → a "Searching…" line) as well as
  // query-to-query edits (dim the results already on screen). Sub-threshold navs —
  // typing 1–2 chars, or clearing back toward the hint — don't count, since those
  // skip the backend.
  let searching = $derived(
    navigating.to?.route.id === '/search' && queryInput.trim().length >= MIN_SEARCH_QUERY_LENGTH,
  );
</script>

<svelte:head>
  <title>{pageTitle('Search')}</title>
</svelte:head>

<div class="search-page">
  <SearchBox
    bind:value={queryInput}
    placeholder="Search titles, manufacturers, people..."
    autofocus
  />

  {#if !searching && data.q.length > 0 && data.q.length < MIN_SEARCH_QUERY_LENGTH}
    <p class="hint">Type at least {MIN_SEARCH_QUERY_LENGTH} characters to search</p>
  {:else if data.results}
    <div class="results" class:pending={searching}>
      <SearchResults results={data.results} q={data.q} />
    </div>
  {:else if searching}
    <p class="hint">Searching…</p>
  {/if}
</div>

<style>
  .search-page {
    padding: var(--size-5) 0;
  }

  .hint {
    text-align: center;
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
    margin-top: var(--size-2);
  }

  .results {
    transition: opacity 0.15s var(--ease-2);
  }

  .results.pending {
    opacity: 0.55;
  }
</style>
