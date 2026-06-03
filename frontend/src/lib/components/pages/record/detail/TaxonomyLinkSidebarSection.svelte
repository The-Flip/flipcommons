<script lang="ts">
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarListItem from '$lib/components/layout/page/sidebar/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import { resolveHref } from '$lib/utils';

  let {
    heading,
    basePath,
    item,
    onEdit = undefined,
  }: {
    heading: string;
    /** Section prefix, e.g. '/franchises' or '/series'. */
    basePath: string;
    item: { public_id: string; name: string } | null | undefined;
    onEdit?: (() => void) | undefined;
  } = $props();
</script>

{#if item}
  <SidebarSection {heading} {onEdit}>
    <SidebarList>
      <SidebarListItem>
        <a href={resolveHref(`${basePath}/${item.public_id}`)}>{item.name}</a>
      </SidebarListItem>
    </SidebarList>
  </SidebarSection>
{/if}
