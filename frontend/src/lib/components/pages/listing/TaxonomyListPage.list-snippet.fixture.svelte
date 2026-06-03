<script lang="ts">
  import { ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';
  import TaxonomyListPage from './TaxonomyListPage.svelte';

  type Item = { slug: string; name: string; aliases?: string[] };

  let {
    catalogKey = 'tag',
    subtitle,
    items,
    canCreate = false,
  }: {
    catalogKey?: CatalogEntityKey;
    subtitle?: string;
    items: Item[];
    canCreate?: boolean;
  } = $props();

  let basePath = $derived(`/${ENTITY_META[catalogKey].entity_type_plural}`);
</script>

<TaxonomyListPage {catalogKey} {subtitle} {items} {canCreate}>
  {#snippet listSnippet(shown)}
    <ul class="item-list">
      {#each shown as item (item.slug)}
        <li><a class="item-row" href={`${basePath}/${item.slug}`}>{item.name}</a></li>
      {/each}
    </ul>
  {/snippet}
</TaxonomyListPage>
