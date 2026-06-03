<script lang="ts">
  import CatalogListing from './CatalogListing.svelte';
  import PersonCard from '$lib/components/cards/PersonCard.svelte';

  type Card = { slug: string; name: string; thumbnail_url: string | null; credit_count: number };

  let {
    initial,
    q = '',
    canCreate = false,
    fetchPage = () => Promise.resolve({ items: [], count: 0 }),
  }: {
    initial: { items: Card[]; count: number };
    q?: string;
    canCreate?: boolean;
    fetchPage?: (page: number) => Promise<{ items: Card[]; count: number }>;
  } = $props();
</script>

<CatalogListing catalogKey="person" layout="card" {initial} {q} {fetchPage} {canCreate}>
  {#snippet children(person)}
    <PersonCard
      slug={person.slug}
      name={person.name}
      thumbnailUrl={person.thumbnail_url}
      creditCount={person.credit_count}
    />
  {/snippet}
</CatalogListing>
