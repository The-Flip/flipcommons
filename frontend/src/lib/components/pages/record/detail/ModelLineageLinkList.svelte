<!-- @component Renders a list of model lineage links (name + year) as a plain `<ul>`. Shared by the mobile model relationships list and the single-model title page; the desktop sidebar renders its own list via `SidebarList`. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import type { ModelLineageLink } from '$lib/entities/model-lineage';

  let { links }: { links: ModelLineageLink[] } = $props();
</script>

<ul class="lineage-links">
  {#each links as link (link.public_id)}
    <li>
      <a href={resolve('/models/[slug]', { slug: link.public_id })}>{link.name}</a>
      {#if link.year}
        <span class="muted">({link.year})</span>
      {/if}
    </li>
  {/each}
</ul>

<style>
  .lineage-links {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .lineage-links li {
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }
</style>
