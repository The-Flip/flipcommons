<script lang="ts">
  import ClientFilteredGrid from '$lib/components/collections/grid/ClientFilteredGrid.svelte';
  import ManufacturerCard from '$lib/components/collections/cards/ManufacturerCard.svelte';

  let {
    manufacturers,
    showCount = true,
  }: {
    manufacturers: {
      name: string;
      public_id: string;
      model_count: number;
      thumbnail_url?: string | null;
    }[];
    showCount?: boolean;
  } = $props();
</script>

<ClientFilteredGrid items={manufacturers} entityName="manufacturer" {showCount}>
  {#snippet children(mfr)}
    <ManufacturerCard
      slug={mfr.public_id}
      name={mfr.name}
      thumbnailUrl={mfr.thumbnail_url}
      modelCount={mfr.model_count}
    />
  {/snippet}
</ClientFilteredGrid>
