<script lang="ts">
  import { resolveHref } from '$lib/utils';
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarListItem from '$lib/components/layout/page/sidebar/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import type { EntityRef } from '$lib/api/schema';

  let {
    basePath,
    parents,
    children,
    aliases,
    parentHeading,
    childHeading,
    aliasHeading = 'Also known as',
  }: {
    basePath: string;
    parents: EntityRef[];
    children: EntityRef[];
    aliases: string[];
    parentHeading: string;
    childHeading: string;
    aliasHeading?: string;
  } = $props();
</script>

{#if parents.length > 0}
  <SidebarSection heading={parentHeading}>
    <SidebarList>
      {#each parents as parent (parent.public_id)}
        <SidebarListItem>
          <a href={resolveHref(`${basePath}/${parent.public_id}`)}>{parent.name}</a>
        </SidebarListItem>
      {/each}
    </SidebarList>
  </SidebarSection>
{/if}

{#if children.length > 0}
  <SidebarSection heading={childHeading}>
    <SidebarList>
      {#each children as child (child.public_id)}
        <SidebarListItem>
          <a href={resolveHref(`${basePath}/${child.public_id}`)}>{child.name}</a>
        </SidebarListItem>
      {/each}
    </SidebarList>
  </SidebarSection>
{/if}

{#if aliases.length > 0}
  <SidebarSection heading={aliasHeading}>
    <p class="aliases">{aliases.join(', ')}</p>
  </SidebarSection>
{/if}

<style>
  .aliases {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0;
  }
</style>
