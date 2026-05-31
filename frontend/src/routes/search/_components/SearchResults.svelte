<script lang="ts">
  import { SvelteSet } from 'svelte/reactivity';
  import client from '$lib/api/client';
  import { createAsyncLoader } from '$lib/async-loader.svelte';
  import CardGrid from '$lib/components/grid/CardGrid.svelte';
  import ManufacturerCard from '$lib/components/cards/ManufacturerCard.svelte';
  import PersonCard from '$lib/components/cards/PersonCard.svelte';
  import TitleCard from '$lib/components/cards/TitleCard.svelte';
  import { normalizeText } from '$lib/utils';

  const MIN_QUERY_LENGTH = 2;
  const PREVIEW_SIZE = 5;

  let { query }: { query: string } = $props();

  let expanded: Record<string, boolean> = $state({});

  const titles = createAsyncLoader(async () => {
    const { data } = await client.GET('/api/titles/all/');
    return data ?? [];
  }, []);

  const manufacturers = createAsyncLoader(async () => {
    const { data } = await client.GET('/api/manufacturers/all/');
    return data ?? [];
  }, []);

  const models = createAsyncLoader(async () => {
    const { data } = await client.GET('/api/models/all/');
    return data ?? [];
  }, []);

  const people = createAsyncLoader(async () => {
    const { data } = await client.GET('/api/people/all/');
    return data ?? [];
  }, []);

  // Reset expanded when query changes
  $effect(() => {
    void query;
    expanded = {};
  });

  let normalizedQuery = $derived(normalizeText(query.trim()));
  let isSearching = $derived(normalizedQuery.length >= MIN_QUERY_LENGTH);

  function textMatches(q: string, ...fields: (string | number | null | undefined)[]): boolean {
    return fields.some((f) => f != null && normalizeText(String(f)).includes(q));
  }

  let matchedModels = $derived.by(() => {
    if (!isSearching) return [];
    return models.data.filter(
      (m) =>
        textMatches(normalizedQuery, m.name, ...(m.abbreviations ?? [])) ||
        (m.search_text && normalizeText(m.search_text).includes(normalizedQuery)),
    );
  });

  // Title slugs from matched models for roll-up
  let rollupTitleSlugs = $derived.by(() => {
    const slugs = new SvelteSet<string>();
    for (const m of matchedModels) {
      if (m.title_slug) slugs.add(m.title_slug);
    }
    return slugs;
  });

  let matchedTitles = $derived.by(() => {
    if (!isSearching) return [];
    return titles.data.filter(
      (t) =>
        textMatches(normalizedQuery, t.name, ...(t.abbreviations ?? [])) ||
        rollupTitleSlugs.has(t.slug),
    );
  });

  let matchedManufacturers = $derived.by(() => {
    if (!isSearching) return [];
    return manufacturers.data.filter(
      (m) =>
        textMatches(normalizedQuery, m.name) ||
        (m.search_text && normalizeText(m.search_text).includes(normalizedQuery)),
    );
  });

  let matchedPeople = $derived.by(() => {
    if (!isSearching) return [];
    return people.data.filter((p) => textMatches(normalizedQuery, p.name));
  });

  let totalResults = $derived(
    matchedTitles.length + matchedManufacturers.length + matchedPeople.length,
  );

  let anyLoading = $derived(
    titles.loading || models.loading || manufacturers.loading || people.loading,
  );

  function toggleGroup(group: string) {
    expanded[group] = !expanded[group];
  }
</script>

{#if query.trim().length > 0 && query.trim().length < MIN_QUERY_LENGTH}
  <p class="hint">Type at least {MIN_QUERY_LENGTH} characters to search</p>
{/if}

{#if isSearching}
  <div class="results-summary">
    {#if anyLoading}
      <p class="count">Searching...</p>
    {:else}
      <p class="count">
        {totalResults.toLocaleString()} result{totalResults === 1 ? '' : 's'}
      </p>
    {/if}
  </div>

  {#if matchedTitles.length > 0}
    {@const showAll = expanded['titles']}
    {@const items = showAll ? matchedTitles : matchedTitles.slice(0, PREVIEW_SIZE)}
    <section class="result-group">
      <h2>Titles <span class="group-count">{matchedTitles.length}</span></h2>
      <CardGrid>
        {#each items as title (title.slug)}
          <TitleCard
            slug={title.slug}
            name={title.name}
            thumbnailUrl={title.thumbnail_url}
            manufacturerName={title.manufacturer?.name}
            year={title.year}
          />
        {/each}
      </CardGrid>
      {#if matchedTitles.length > PREVIEW_SIZE}
        <button class="see-all" onclick={() => toggleGroup('titles')}>
          {showAll ? 'Show less' : `See all ${matchedTitles.length.toLocaleString()} titles`}
        </button>
      {/if}
    </section>
  {/if}

  {#if matchedManufacturers.length > 0}
    {@const showAll = expanded['manufacturers']}
    {@const items = showAll ? matchedManufacturers : matchedManufacturers.slice(0, PREVIEW_SIZE)}
    <section class="result-group">
      <h2>
        Manufacturers <span class="group-count">{matchedManufacturers.length}</span>
      </h2>
      <CardGrid>
        {#each items as mfr (mfr.slug)}
          <ManufacturerCard
            slug={mfr.slug}
            name={mfr.name}
            thumbnailUrl={mfr.thumbnail_url}
            modelCount={mfr.model_count}
          />
        {/each}
      </CardGrid>
      {#if matchedManufacturers.length > PREVIEW_SIZE}
        <button class="see-all" onclick={() => toggleGroup('manufacturers')}>
          {showAll
            ? 'Show less'
            : `See all ${matchedManufacturers.length.toLocaleString()} manufacturers`}
        </button>
      {/if}
    </section>
  {/if}

  {#if matchedPeople.length > 0}
    {@const showAll = expanded['people']}
    {@const items = showAll ? matchedPeople : matchedPeople.slice(0, PREVIEW_SIZE)}
    <section class="result-group">
      <h2>People <span class="group-count">{matchedPeople.length}</span></h2>
      <CardGrid>
        {#each items as person (person.slug)}
          <PersonCard
            slug={person.slug}
            name={person.name}
            thumbnailUrl={person.thumbnail_url}
            creditCount={person.credit_count}
          />
        {/each}
      </CardGrid>
      {#if matchedPeople.length > PREVIEW_SIZE}
        <button class="see-all" onclick={() => toggleGroup('people')}>
          {showAll ? 'Show less' : `See all ${matchedPeople.length.toLocaleString()} people`}
        </button>
      {/if}
    </section>
  {/if}

  {#if !anyLoading && totalResults === 0}
    <p class="no-results">No results found for "{query.trim()}"</p>
  {/if}
{/if}

<style>
  .hint {
    text-align: center;
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
    margin-top: var(--size-2);
  }

  .results-summary {
    text-align: center;
    margin-bottom: var(--size-4);
  }

  .count {
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
  }

  .result-group {
    margin-bottom: var(--size-6);
  }

  .result-group h2 {
    font-size: var(--font-size-4);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
    display: flex;
    align-items: baseline;
    gap: var(--size-2);
  }

  .group-count {
    font-size: var(--font-size-1);
    font-weight: 400;
    color: var(--color-text-muted);
  }

  .see-all {
    display: block;
    margin: var(--size-3) auto 0;
    padding: var(--size-2) var(--size-4);
    background: none;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    color: var(--color-link);
    font-size: var(--font-size-1);
    cursor: pointer;
    transition:
      background-color 0.15s ease,
      border-color 0.15s ease;
  }

  .see-all:hover {
    background-color: var(--color-surface);
    border-color: var(--color-link);
  }

  .no-results {
    text-align: center;
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
  }
</style>
