<script lang="ts">
  import { resolve } from '$app/paths';
  import SidebarList from './SidebarList.svelte';
  import SidebarSection from './SidebarSection.svelte';

  interface Variant {
    name: string;
    public_id: string;
    year?: number | null;
  }

  interface Model {
    name: string;
    public_id: string;
    year?: number | null;
    variants: Variant[];
  }

  let {
    models,
    heading = 'Models',
    currentSlug = undefined,
    variantOfSlug = undefined,
    excludeSlug = undefined,
    inline = false,
  }: {
    models: Model[];
    heading?: string;
    currentSlug?: string;
    variantOfSlug?: string;
    excludeSlug?: string;
    inline?: boolean;
  } = $props();

  function sortedVariants(variants: Variant[]): Variant[] {
    return [...variants].sort((a, b) => (a.year ?? 0) - (b.year ?? 0));
  }

  let filteredModels = $derived(
    excludeSlug ? models.filter((m) => m.public_id !== excludeSlug) : models,
  );
</script>

{#snippet listItems()}
  {#each filteredModels as parent (parent.public_id)}
    <li
      class:current={currentSlug !== undefined &&
        (parent.public_id === currentSlug || parent.public_id === variantOfSlug)}
    >
      <a href={resolve(`/models/${parent.public_id}`)}>{parent.name}</a>
      {#if parent.year}
        <span class="muted">{parent.year}</span>
      {/if}
    </li>
    {#each sortedVariants(parent.variants) as variant (variant.public_id)}
      <li
        class="variant-indent"
        class:current={currentSlug !== undefined && variant.public_id === currentSlug}
      >
        <a href={resolve(`/models/${variant.public_id}`)}>{variant.name}</a>
        {#if variant.year}
          <span class="muted">{variant.year}</span>
        {/if}
      </li>
    {/each}
  {/each}
{/snippet}

{#if filteredModels.length > 0}
  {#if inline}
    <div class="relationship-group">
      <h3>{heading}</h3>
      <ul>
        {@render listItems()}
      </ul>
    </div>
  {:else}
    <SidebarSection {heading}>
      <SidebarList>
        {@render listItems()}
      </SidebarList>
    </SidebarSection>
  {/if}
{/if}

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

  .relationship-group ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  li {
    display: flex;
    align-items: baseline;
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }

  li > a {
    flex: 1;
  }

  li:not(:last-child):not(.variant-indent):not(:has(+ .variant-indent)) {
    border-bottom: 1px solid var(--color-border-soft);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  .variant-indent {
    margin-left: var(--size-4);
  }

  .variant-indent::before {
    content: '└';
    margin-right: var(--size-2);
    color: var(--color-text-muted);
  }

  .current > a {
    font-weight: 600;
    color: var(--color-link);
  }
</style>
