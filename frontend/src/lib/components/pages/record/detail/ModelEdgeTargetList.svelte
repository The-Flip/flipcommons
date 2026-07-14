<!-- @component Renders one relationship-edge section's target lines as a plain `<ul>` — a machine target links as a whole ("Galaxie (Gottlieb 1971)"), a label target is plain text with no hyperlink. Shared by the mobile relationships list and the desktop sidebar sections. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import type { ModelEdgeTargetView } from '$lib/entities/model-lineage';

  let { targets }: { targets: ModelEdgeTargetView[] } = $props();
</script>

<ul class="edge-targets">
  {#each targets as target (target.machine?.public_id ?? target.label)}
    <li>
      {#if target.machine}
        <a href={resolve('/models/[slug]', { slug: target.machine.public_id })}
          >{target.machine.text}</a
        >
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
