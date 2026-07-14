<!-- @component Renders a list of model lineage links as a plain `<ul>` of `RelatedModelLink` lines. Shared by the mobile model relationships list and the single-model title page; the desktop sidebar renders its own list via `SidebarList`. -->
<script lang="ts">
  import RelatedModelLink from './RelatedModelLink.svelte';
  import type { ModelLineageLinkView } from '$lib/entities/model-lineage';

  let { links }: { links: ModelLineageLinkView[] } = $props();
</script>

<ul class="lineage-links">
  {#each links as link (link.public_id)}
    <li>
      <RelatedModelLink {link} />
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
</style>
