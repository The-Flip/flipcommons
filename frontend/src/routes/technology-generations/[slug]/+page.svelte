<script lang="ts">
  import client from '$lib/api/client';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import MachineCard from '$lib/components/collections/cards/MachineCard.svelte';
  import PaginatedSection from '$lib/components/collections/grid/PaginatedSection.svelte';
  import { createPaginatedLoader, unwrapPage } from '$lib/paginated-loader.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);

  const machines = createPaginatedLoader(async (page) => {
    const { data: result } = await client.GET('/api/models/', {
      params: { query: { type: profile.slug, page } },
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

<PaginatedSection loader={machines} heading="Machines" emptyMessage="No machines of this type.">
  {#snippet children(machine)}
    <MachineCard
      slug={machine.slug}
      name={machine.name}
      thumbnailUrl={machine.thumbnail_url}
      manufacturerName={machine.manufacturer?.name}
      year={machine.year}
    />
  {/snippet}
</PaginatedSection>

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
