<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import EditSectionShell from '$lib/components/pages/record/edit/EditSectionShell.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import {
    defaultSystemSectionSegment,
    findSystemSectionBySegment,
    SYSTEM_EDIT_SECTIONS,
  } from '$lib/components/editors/system-edit-sections';
  import { setEditLayoutContext } from '$lib/components/editors/edit-layout-context';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';

  let { children } = $props();
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let currentSection = $derived(
    sectionSegment ? findSystemSectionBySegment(sectionSegment) : undefined,
  );
  let editorDirty = $state(false);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  setEditLayoutContext({
    setDirty(dirty: boolean) {
      editorDirty = dirty;
    },
  });

  let switcherItems: EditSectionMenuItem[] = $derived(
    SYSTEM_EDIT_SECTIONS.map((section) => ({
      key: section.key,
      label: section.label,
      href: resolve(`/systems/${slug}/edit/${section.segment}`),
    })),
  );

  $effect(() => {
    if (isMobile !== false) return;
    const segment = currentSection?.segment ?? defaultSystemSectionSegment();
    goto(resolve(`/systems/${slug}?edit=${segment}`), { replaceState: true });
  });
</script>

{#if isMobile === true}
  <EditSectionShell
    detailHref={resolve(`/systems/${slug}`)}
    {switcherItems}
    currentSectionKey={currentSection?.key}
    {editorDirty}
  >
    {@render children()}
  </EditSectionShell>
{/if}
