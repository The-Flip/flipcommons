<!-- @component Renders a model's model↔model lineage relations, then its relationship-edge sections (copy / conversion / kit, outbound then inbound), as `SidebarSection`s — the desktop sidebar presentation. Shared by the model page and the single-model title page; the mobile presentation is `ModelLineageGroups`. -->
<script lang="ts">
  import RelatedModelLink from './RelatedModelLink.svelte';
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarListItem from '$lib/components/layout/page/sidebar/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import { modelEdgeSections, modelLineageSections } from '$lib/entities/model-lineage';
  import type { ModelDetailSchema } from '$lib/api/schema';

  let { model }: { model: ModelDetailSchema } = $props();
</script>

{#each modelLineageSections(model) as { relation, links } (relation.key)}
  <SidebarSection heading={relation.heading} note={relation.note}>
    <SidebarList>
      {#each links as link (link.public_id)}
        <SidebarListItem>
          <RelatedModelLink {link} />
        </SidebarListItem>
      {/each}
    </SidebarList>
  </SidebarSection>
{/each}

{#each modelEdgeSections(model) as { key, heading, note, targets } (key)}
  <SidebarSection {heading} {note}>
    <SidebarList>
      {#each targets as target (target.machine?.public_id ?? target.label)}
        <SidebarListItem>
          {#if target.machine}
            <RelatedModelLink link={target.machine} />
          {:else}
            {target.label}
          {/if}
        </SidebarListItem>
      {/each}
    </SidebarList>
  </SidebarSection>
{/each}
