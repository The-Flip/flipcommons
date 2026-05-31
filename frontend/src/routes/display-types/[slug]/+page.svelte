<script lang="ts">
  import client from '$lib/api/client';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/Markdown.svelte';
  import TitleCard from '$lib/components/cards/TitleCard.svelte';
  import PaginatedSection from '$lib/components/grid/PaginatedSection.svelte';
  import { createPaginatedLoader } from '$lib/paginated-loader.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);

  const titles = createPaginatedLoader(async (page) => {
    const { data: result } = await client.GET('/api/titles/', {
      params: { query: { display: profile.slug, page } },
    });
    return result ?? { items: [], count: 0 };
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
    <TitleCard
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
