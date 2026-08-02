<!-- @component The /search page: a debounced search box over the cross-entity results of `?q=`. -->
<script lang="ts">
  import { goto } from '$app/navigation';
  import { navigating } from '$app/state';
  import { resolve } from '$app/paths';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import SearchResults from './_components/SearchResults.svelte';
  import { MIN_SEARCH_QUERY_LENGTH, pageTitle } from '$lib/constants';
  import { searchDraft } from '$lib/search-draft.svelte';

  let { data } = $props();

  const queryDraft = searchDraft(
    () => data.q,
    (next) => {
      const search = next ? `?q=${encodeURIComponent(next)}` : '';
      void goto(`${resolve('/search')}${search}`, {
        keepFocus: true,
        // One history entry for a multi-character query, not one per keystroke-pause.
        replaceState: true,
        noScroll: true,
      });
    },
  );

  // A real (≥ MIN) query whose SSR load is in flight. Keyed off the live draft,
  // so it's true the moment the debounced `goto` starts — covering the FIRST
  // query (no prior results to dim yet → a "Searching…" line) as well as
  // query-to-query edits (dim the results already on screen). Sub-threshold navs —
  // typing 1–2 chars, or clearing back toward the hint — don't count, since those
  // skip the backend.
  let searching = $derived(
    navigating.to?.route.id === '/search' &&
      queryDraft.value.trim().length >= MIN_SEARCH_QUERY_LENGTH,
  );
</script>

<svelte:head>
  <title>{pageTitle('Search')}</title>
</svelte:head>

<div class="search-page">
  <SearchBox
    bind:value={queryDraft.value}
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
