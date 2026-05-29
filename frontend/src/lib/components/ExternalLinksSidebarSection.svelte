<script lang="ts">
  import SidebarSection from './SidebarSection.svelte';
  import type { ExternalLink } from '$lib/entities/external-links';

  let {
    links,
    note = 'See this on other sites:',
    onEdit = undefined,
  }: {
    links: ExternalLink[];
    note?: string;
    onEdit?: (() => void) | undefined;
  } = $props();
</script>

{#if links.length}
  <SidebarSection heading="External Links" {note} {onEdit}>
    <div class="external-ids">
      {#each links as link (link.href)}
        <a href={link.href}>{link.label}</a>
      {/each}
    </div>
  </SidebarSection>
{/if}

<style>
  .external-ids {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-3);
    font-size: var(--font-size-0);
  }
</style>
