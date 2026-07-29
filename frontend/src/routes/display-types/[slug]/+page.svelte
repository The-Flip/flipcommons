<script lang="ts">
  import client from '$lib/api/client';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';
  import PaginatedSection from '$lib/components/collections/grid/PaginatedSection.svelte';
  import { createPaginatedLoader, unwrapPage } from '$lib/paginated-loader.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);

  const titles = createPaginatedLoader(async (page) => {
    const { data: result } = await client.GET('/api/titles/', {
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

<PaginatedSection loader={titles} heading="Titles" emptyMessage="No titles with this display type.">
  {#snippet children(title)}
    <GameCard
      entityType="title"
      slug={title.slug}
      name={title.name}
      thumbnailUrl={title.thumbnail_url}
      manufacturerName={title.manufacturer?.name}
      year={title.year}
    />
  {/snippet}
</PaginatedSection>

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
