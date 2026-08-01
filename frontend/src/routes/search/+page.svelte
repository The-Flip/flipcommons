<!-- @component The /search page: a debounced search box over the cross-entity results of `?q=`. -->
<script lang="ts">
  import { goto } from '$app/navigation';
  import { navigating } from '$app/state';
  import { resolve } from '$app/paths';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import SearchResults from './_components/SearchResults.svelte';
  import { MIN_SEARCH_QUERY_LENGTH, pageTitle } from '$lib/constants';

  let { data } = $props();

  // SearchBox binds here. The draft is its own state, not a mirror of `data.q`:
  // the committed value changes exactly when a debounced navigation lands,
  // which is exactly when a still-typing user has a longer draft in the box.
  // svelte-ignore state_referenced_locally
  let queryInput = $state(data.q);

  /** The scheduled commit of the current draft; `undefined` when the draft has
   * nothing left to commit, i.e. the user is not ahead of the committed `q`. */
  let timer: ReturnType<typeof setTimeout> | undefined;

  // Adopt the committed value, but only when the user isn't ahead of it, so a
  // navigation landing mid-word leaves the draft alone. Back/forward and other
  // outside changes have no commit scheduled, so the box follows the URL.
  // Ordered before the debounce below, which re-arms on a committed change and
  // would otherwise make every such change look like the user typing.
  $effect(() => {
    const committed = data.q;
    if (timer !== undefined) return;
    queryInput = committed;
  });

  // Debounce typing → one `goto ?q=` per pause, which re-runs the SSR load.
  // `replaceState` so typing a multi-character query leaves a single history
  // entry, not one per keystroke-pause. Skipped when the input already matches
  // the committed `q` (the seed, or the landing of our own goto) so there's no
  // echo loop.
  $effect(() => {
    const next = queryInput.trim();
    if (next === data.q) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      const search = next ? `?q=${encodeURIComponent(next)}` : '';
      void goto(`${resolve('/search')}${search}`, {
        keepFocus: true,
        replaceState: true,
        noScroll: true,
      });
    }, 250);
    return () => {
      clearTimeout(timer);
      timer = undefined;
    };
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
    placeholder="Search games, manufacturers, people..."
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
