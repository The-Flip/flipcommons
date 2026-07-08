<!-- @component Mobile "Related Models" list: the parent Title plus every model↔model lineage relation (via the shared `ModelLineageGroups`). -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import ModelLineageGroups from '$lib/components/pages/record/detail/ModelLineageGroups.svelte';
  import type { ModelDetailSchema } from '$lib/api/schema';

  let { model }: { model: ModelDetailSchema } = $props();
</script>

{#if model.title}
  <div class="relationship-group">
    <h3>Parent Title</h3>
    <ul class="title-link">
      <li>
        <a href={resolve('/titles/[slug]', { slug: model.title.public_id })}>{model.title.name}</a>
      </li>
    </ul>
  </div>
{/if}

<ModelLineageGroups {model} />

<style>
  .relationship-group {
    margin-bottom: var(--size-3);
  }

  .relationship-group h3 {
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 0 0 var(--size-1);
  }

  .title-link {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .title-link li {
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }
</style>
