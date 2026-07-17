<!-- @component Renders one relationship-edge section's target lines as a plain `<ul>` — a machine target as a `RelatedModelLink` line, a label target as plain text with no hyperlink. -->
<script lang="ts">
  import RelatedModelLink from './RelatedModelLink.svelte';
  import type { ModelEdgeTargetView } from '$lib/entities/model-lineage';

  let { targets }: { targets: ModelEdgeTargetView[] } = $props();
</script>

<ul class="edge-targets">
  {#each targets as target (target.machine?.public_id ?? target.label)}
    <li>
      {#if target.machine}
        <RelatedModelLink link={target.machine} />
      {:else}
        {target.label}
      {/if}
    </li>
  {/each}
</ul>

<style>
  .edge-targets {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .edge-targets li {
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }
</style>
