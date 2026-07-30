<script lang="ts">
  import client from '$lib/api/client';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';
  import PaginatedSection from '$lib/components/collections/grid/PaginatedSection.svelte';
  import { createPaginatedLoader, unwrapPage } from '$lib/paginated-loader.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);

  const games = createPaginatedLoader(async (page) => {
    const { data: result } = await client.GET('/api/games/', {
      params: { query: { display_type: profile.slug, page } },
    });
    return unwrapPage(result);
  });
</script>

{#if profile.description?.html}
  <section class="description">
    <Markdown html={profile.description.html} citations={profile.description.citations ?? []} />
    <AttributionLine attribution={profile.description.attribution} />
  </section>
{/if}

<PaginatedSection loader={games} heading="Games" emptyMessage="No games with this display type.">
  {#snippet children(game)}
    <GameCard
      entityType={game.entity_type}
      slug={game.slug}
      name={game.name}
      thumbnailUrl={game.thumbnail_url}
      manufacturerName={game.manufacturer?.name}
      year={game.year}
    />
  {/snippet}
</PaginatedSection>

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
