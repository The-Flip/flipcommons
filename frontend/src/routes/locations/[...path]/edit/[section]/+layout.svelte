<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import EditSectionShell from '$lib/components/pages/record/edit/EditSectionShell.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import {
    defaultLocationSectionSegment,
    findLocationSectionBySegment,
    locationEditSectionsFor,
  } from '$lib/components/pages/record/edit/editors/entity/location/location-edit-sections';
  import { setEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { LocationDetailSchema } from '$lib/api/schema';

  let { data, children } = $props();
  let profile = $derived<LocationDetailSchema>(data.profile);
  let path = $derived(page.params.path);
  let sectionSegment = $derived(page.params.section);
  let currentSection = $derived(
    sectionSegment ? findLocationSectionBySegment(sectionSegment) : undefined,
  );
  let visibleSections = $derived(locationEditSectionsFor(profile.location_type));
  let editorDirty = $state(false);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  setEditLayoutContext({
    setDirty(dirty: boolean) {
      editorDirty = dirty;
    },
  });

  let switcherItems: EditSectionMenuItem[] = $derived(
    visibleSections.map((section) => ({
      key: section.key,
      label: section.label,
      href: resolve(`/locations/${path}/edit/${section.segment}`),
    })),
  );

  $effect(() => {
    if (isMobile !== false) return;
    const segment = currentSection?.segment ?? defaultLocationSectionSegment();
    goto(`${resolve(`/locations/${path}`)}?edit=${segment}`, { replaceState: true });
  });
</script>

{#if isMobile === true}
  <EditSectionShell
    detailHref={resolve(`/locations/${path}`)}
    {switcherItems}
    currentSectionKey={currentSection?.key}
    {editorDirty}
  >
    {@render children()}
  </EditSectionShell>
{/if}
