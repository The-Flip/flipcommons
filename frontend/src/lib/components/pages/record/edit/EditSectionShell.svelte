<script lang="ts">
  import type { Snippet } from 'svelte';
  import EditSectionMenu from '$lib/components/layout/page/EditSectionMenu.svelte';
  import FocusContentShell from '$lib/components/layout/page/FocusContentShell.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import { getEntityContext } from '$lib/entity-context';

  let {
    detailHref,
    switcherItems,
    currentSectionKey = undefined,
    editorDirty = false,
    fallbackHeading = 'Edit',
    children,
  }: {
    detailHref: string;
    switcherItems: EditSectionMenuItem[];
    currentSectionKey?: string;
    editorDirty?: boolean;
    fallbackHeading?: string;
    children: Snippet;
  } = $props();

  const entity = getEntityContext();
</script>

<FocusContentShell backHref={detailHref} recordName={entity.name} recordHref={entity.detailHref}>
  {#snippet heading()}
    {#if currentSectionKey}
      <EditSectionMenu
        items={switcherItems}
        currentKey={currentSectionKey}
        disabled={editorDirty}
        variant="heading"
      />
    {:else}
      <h1 class="fallback-heading">{fallbackHeading}</h1>
    {/if}
  {/snippet}

  {@render children()}
</FocusContentShell>

<style>
  .fallback-heading {
    font-size: var(--font-size-3);
    font-weight: 600;
    margin: 0;
  }
</style>
