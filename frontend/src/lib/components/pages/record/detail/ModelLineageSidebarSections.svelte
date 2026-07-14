<!-- @component Renders a model's model↔model lineage relations, then its relationship-edge sections (copy / conversion / kit, outbound then inbound), as `SidebarSection`s — the desktop sidebar presentation. Shared by the model page and the single-model title page; the mobile presentation is `ModelLineageGroups`. -->
<script lang="ts">
  import { resolve } from '$app/paths';
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
          <a href={resolve('/models/[slug]', { slug: link.public_id })}>{link.name}</a>
          {#if link.manufacturer || link.year}
            <span class="muted">
              {#if link.manufacturer}<a
                  class="maker"
                  href={resolve('/manufacturers/[slug]', { slug: link.manufacturer.public_id })}
                  >{link.manufacturer.name}</a
                >{/if}{#if link.manufacturer && link.year}&nbsp;·&nbsp;{/if}{#if link.year}{link.year}{/if}
            </span>
          {/if}
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
            <a href={resolve('/models/[slug]', { slug: target.machine.public_id })}
              >{target.machine.text}</a
            >
          {:else}
            {target.label}
          {/if}
        </SidebarListItem>
      {/each}
    </SidebarList>
  </SidebarSection>
{/each}

<style>
  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  /* Maker link reads as supplementary: link-colored but at the muted size. */
  .maker {
    font-size: var(--font-size-0);
  }
</style>
