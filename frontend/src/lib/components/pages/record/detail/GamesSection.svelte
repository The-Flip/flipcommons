<!-- @component
Detail-page games section: the /games listing pinned to one dimension value.
SSR-seeded page 1 + count from the page payload's `games` embed, pages 2+
from `GET /api/games/` with the pin (and any active search) applied, and a
threshold-gated search box that mirrors typing into a debounced `goto ?q=` —
the listing page's own mechanism, so the server load re-runs and reseeds. -->
<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import client from '$lib/api/client';
  import type { GameCardSchema, paths } from '$lib/api/schema';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';
  import { SEARCH_THRESHOLD } from '$lib/components/collections/grid/search-threshold';
  import PaginatedCardLoader from '$lib/components/pages/listing/PaginatedCardLoader.svelte';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import { unwrapPage } from '$lib/paginated-loader.svelte';

  /** The listing query params that pin the section to its dimension value. */
  type GamesQuery = NonNullable<paths['/api/games/']['get']['parameters']['query']>;

  let {
    games,
    q,
    pinned,
    showManufacturer = true,
  }: {
    /** SSR page 1 + total count for the committed `q` — the page payload's embed. */
    games: { items: GameCardSchema[]; count: number };
    /** Committed search term from the SSR load (URL-derived); '' when unfiltered. */
    q: string;
    /** The pinned dimension params, e.g. `{ theme: [slug] }`. */
    pinned: GamesQuery;
    /** False on pages whose subject is the maker (manufacturer, corporate entity). */
    showManufacturer?: boolean;
  } = $props();

  const fetchPage = async (pageNum: number) => {
    const { data } = await client.GET('/api/games/', {
      params: { query: { ...pinned, ...(q ? { q } : {}), page: pageNum } },
    });
    return unwrapPage(data);
  };

  // SearchBox binds here — a writable `$derived` so it mirrors the committed
  // `q` on seed/popstate/goto-landing yet stays reassignable while typing.
  let queryInput = $derived(q);

  // Debounce typing → one `goto ?q=` per pause on the page's own path. The
  // navigation re-runs the server load, which reseeds `games` and `q`.
  let qTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const next = queryInput.trim();
    if (next === q) return;
    clearTimeout(qTimer);
    qTimer = setTimeout(() => {
      const href = `${page.url.pathname}${next ? `?q=${encodeURIComponent(next)}` : ''}`;
      void goto(href, { keepFocus: true, noScroll: true });
    }, 250);
    return () => clearTimeout(qTimer);
  });

  // Appears once the set is big enough to need it, or whenever a query is
  // active (so a narrowed result set keeps its box). Server count, not page 1.
  let showSearch = $derived(games.count >= SEARCH_THRESHOLD || q.trim() !== '');
</script>

<section>
  {#if showSearch}
    <SearchBox bind:value={queryInput} placeholder="Search games..." />
  {/if}

  {#if games.count === 0}
    <p class="empty">{q ? 'No matching games.' : 'No games.'}</p>
  {:else}
    <h2>Games ({games.count})</h2>
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
