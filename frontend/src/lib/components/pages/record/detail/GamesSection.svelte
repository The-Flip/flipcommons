<!-- @component
Detail-page games section: the /games listing pinned to one dimension value.
SSR-seeded page 1 + count from the page payload's `games` embed, pages 2+
from `GET /api/games/` with the embed's own `pin` (and any active search)
applied — the pin travels in the payload precisely so this component can
never paginate a different set than page 1 — and a threshold-gated search
box that mirrors typing into a debounced `goto ?q=` — the listing page's
own mechanism, so the server load re-runs and reseeds. -->
<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import client from '$lib/api/client';
  import type { GameListSchema, paths } from '$lib/api/schema';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';
  import { SEARCH_THRESHOLD } from '$lib/components/collections/grid/search-threshold';
  import PaginatedCardLoader from '$lib/components/pages/listing/PaginatedCardLoader.svelte';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import { searchDraft } from '$lib/search-draft.svelte';

  /** The listing query params for pages 2+. */
  type GamesQuery = NonNullable<paths['/api/games/']['get']['parameters']['query']>;

  let {
    games,
    q,
    showManufacturer = true,
  }: {
    /** SSR page 1 + count + pin for the committed `q` — the page payload's embed. */
    games: GameListSchema;
    /** Committed search term from the SSR load (URL-derived); '' when unfiltered. */
    q: string;
    /** False on pages whose subject is the maker (manufacturer, corporate entity). */
    showManufacturer?: boolean;
  } = $props();

  /** The embed's pin as query params: unset dimensions (nulls, empty lists)
   * stripped so they don't serialize. The pin's field names are the listing's
   * own param vocabulary, so the assertion narrows, not remaps. */
  function pinQuery(pin: GameListSchema['pin']): GamesQuery {
    return Object.fromEntries(
      Object.entries(pin).filter(([, v]) => v != null && (!Array.isArray(v) || v.length > 0)),
    ) as GamesQuery;
  }

  const fetchPage = async (pageNum: number) => {
    const { data } = await client.GET('/api/games/', {
      params: { query: { ...pinQuery(games.pin), ...(q ? { q } : {}), page: pageNum } },
    });
    return unwrapPage(data);
  };

  // Commits go to the page's own path, so the server load re-runs and reseeds
  // `games` and `q`.
  const queryDraft = searchDraft(
    () => q,
    (next) => {
      const href = `${page.url.pathname}${next ? `?q=${encodeURIComponent(next)}` : ''}`;
      void goto(href, { keepFocus: true, noScroll: true });
    },
  );

  // Appears once the set is big enough to need it, or whenever a query is
  // active (so a narrowed result set keeps its box). Server count, not page 1.
  let showSearch = $derived(games.count >= SEARCH_THRESHOLD || q.trim() !== '');
</script>

<!-- Hosts an infinite scroller, so this section must be the LAST thing on its
     page — content placed after it is unreachable until every page has been
     scrolled in. -->
<section>
  <h2>Games ({games.count})</h2>

  {#if showSearch}
    <SearchBox bind:value={queryDraft.value} placeholder="Search games..." />
  {/if}

  {#if games.count === 0}
    <p class="empty">{q ? 'No matching games.' : 'No games.'}</p>
  {:else}
    {#key q}
      <PaginatedCardLoader initial={games} {fetchPage}>
        {#snippet children(game)}
          <GameCard
            entityType={game.entity_type}
            publicId={game.public_id}
            name={game.name}
            thumbnailUrl={game.thumbnail_url}
            manufacturerName={game.manufacturer?.name}
            year={game.year}
            roles={game.roles}
            {showManufacturer}
          />
        {/snippet}
      </PaginatedCardLoader>
    {/key}
  {/if}
</section>

<style>
  section {
    /* Breathing room from whatever precedes the section — detail pages place
       it after prose or accordion stacks, neither of which brings a gap. */
    margin-top: var(--size-5);
  }

  h2 {
    font-size: var(--font-size-3);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  .empty {
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
    text-align: center;
  }
</style>
