<!-- @component Global-search results: per-entity card sections with "see all" listing links. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import CardGrid from '$lib/components/collections/grid/CardGrid.svelte';
  import ManufacturerCard from '$lib/components/collections/cards/ManufacturerCard.svelte';
  import PersonCard from '$lib/components/collections/cards/PersonCard.svelte';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';
  import type { SearchResultsSchema } from '$lib/api/schema';

  let { results, q }: { results: SearchResultsSchema; q: string } = $props();

  // A section caps at 10; when `has_more`, link to that entity's listing page,
  // which already does the same server-side `q` search with pagination. So a
  // capped section is a doorway to the full result set, not a dead end.
  const titlesHref = $derived(`${resolve('/games')}?q=${encodeURIComponent(q)}`);
  const manufacturersHref = $derived(`${resolve('/manufacturers')}?q=${encodeURIComponent(q)}`);
  const peopleHref = $derived(`${resolve('/people')}?q=${encodeURIComponent(q)}`);

  const shownCount = $derived(
    results.games.items.length + results.manufacturers.items.length + results.people.items.length,
  );
  const empty = $derived(shownCount === 0);

  // Concise summary for assistive tech. One persistent live region whose text
  // swaps on each load announces just this line once the debounce settles —
  // unlike wrapping the card grid, which would re-read every card per keystroke.
  const statusText = $derived(
    empty ? `No results for "${q}"` : `Showing ${shownCount} result${shownCount === 1 ? '' : 's'}`,
  );
</script>

<p class="visually-hidden" aria-live="polite">{statusText}</p>

{#if empty}
  <!-- aria-hidden: the visually-hidden live region above already announces this
       to assistive tech, so don't read it a second time in the reading order. -->
  <p class="no-results" aria-hidden="true">No results for "{q}"</p>
{:else}
  {#if results.games.items.length > 0}
    <section class="result-group">
      <h2>Games</h2>
      <CardGrid>
        <!-- Composite key: slugs are unique per table, not across tables — a
             Title and a Model can share one, and a mixed section must not
             collide. -->
        {#each results.games.items as game (`${game.entity_type}:${game.public_id}`)}
          <GameCard
            entityType={game.entity_type}
            publicId={game.public_id}
            name={game.name}
            thumbnailUrl={game.thumbnail_url}
            manufacturerName={game.manufacturer?.name}
            year={game.year}
          />
        {/each}
      </CardGrid>
      {#if results.games.has_more}
        <a class="see-all" href={titlesHref}>See all games matching "{q}" →</a>
      {/if}
    </section>
  {/if}

  {#if results.manufacturers.items.length > 0}
    <section class="result-group">
      <h2>Manufacturers</h2>
      <CardGrid>
        {#each results.manufacturers.items as mfr (mfr.slug)}
          <ManufacturerCard
            slug={mfr.slug}
            name={mfr.name}
            thumbnailUrl={mfr.thumbnail_url}
            modelCount={mfr.model_count}
          />
        {/each}
      </CardGrid>
      {#if results.manufacturers.has_more}
        <a class="see-all" href={manufacturersHref}>See all Manufacturers matching "{q}" →</a>
      {/if}
    </section>
  {/if}

  {#if results.people.items.length > 0}
    <section class="result-group">
      <h2>People</h2>
      <CardGrid>
        {#each results.people.items as person (person.slug)}
          <PersonCard
            slug={person.slug}
            name={person.name}
            thumbnailUrl={person.thumbnail_url}
            creditCount={person.credit_count}
          />
        {/each}
      </CardGrid>
      {#if results.people.has_more}
        <a class="see-all" href={peopleHref}>See all People matching "{q}" →</a>
      {/if}
    </section>
  {/if}
{/if}

<style>
  .result-group {
    margin-bottom: var(--size-6);
  }

  .result-group h2 {
    font-size: var(--font-size-4);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  .see-all {
    display: inline-block;
    margin-top: var(--size-3);
    color: var(--color-link);
    font-size: var(--font-size-1);
  }

  .no-results {
    text-align: center;
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
  }
</style>
