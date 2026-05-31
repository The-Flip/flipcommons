<script lang="ts">
  import client from '$lib/api/client';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/Markdown.svelte';
  import MachineCard from '$lib/components/cards/MachineCard.svelte';
  import PaginatedSection from '$lib/components/grid/PaginatedSection.svelte';
  import { createPaginatedLoader } from '$lib/paginated-loader.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);

  const machines = createPaginatedLoader(async (page) => {
    const { data: result } = await client.GET('/api/models/', {
      params: { query: { tag: profile.slug, page } },
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

<PaginatedSection loader={machines} heading="Machines" emptyMessage="No machines with this tag.">
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
