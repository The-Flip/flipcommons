<!-- @component Renders every model↔model lineage relation present on a model as `<h3>` + link-list groups. The mobile lineage presentation (the sidebar renders its own via `SidebarSection`); shared by the model page's Related Models accordion and the single-model title page. -->
<script lang="ts">
  import ModelLineageLinkList from './ModelLineageLinkList.svelte';
  import { modelLineageSections } from '$lib/entities/model-lineage';
  import type { ModelDetailSchema } from '$lib/api/schema';

  let { model }: { model: ModelDetailSchema } = $props();
</script>

{#each modelLineageSections(model) as { relation, links } (relation.key)}
  <div class="relationship-group">
    <h3>{relation.heading}</h3>
    <ModelLineageLinkList {links} />
  </div>
{/each}

<style>
  .relationship-group {
    margin-bottom: var(--size-3);
  }

  .relationship-group:last-child {
    margin-bottom: 0;
  }

  .relationship-group h3 {
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 0 0 var(--size-1);
  }
</style>
