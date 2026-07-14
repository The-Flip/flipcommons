<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditHarness from '$lib/components/pages/record/edit/SectionEditHarness.svelte';
  import {
    defaultLocationSectionSegment,
    findLocationSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/location/location-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { LocationDetailSchema } from '$lib/api/schema';
  import LocationEditorSwitch from '../LocationEditorSwitch.svelte';

  let { data } = $props();
  let profile = $derived<LocationDetailSchema>(data.profile);
  let path = $derived(page.params.path);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(sectionSegment ? findLocationSectionBySegment(sectionSegment) : undefined);
  let sectionAvailable = $derived(
    section !== undefined && (!section.countryOnly || profile.location_type === 'country'),
  );
  // Country-only sections are hidden for non-country locations; only pass the
  // section through when it's actually available here.
  let activeSection = $derived(sectionAvailable ? section : undefined);

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !sectionAvailable) {
      goto(resolve(`/locations/${path}/edit/${defaultLocationSectionSegment()}`), {
        replaceState: true,
      });
    }
  });
</script>

<SectionEditHarness section={activeSection} detailHref={`/locations/${path}`}>
  {#snippet editor({ ref, onsaved, onerror }, activeSection)}
    <LocationEditorSwitch
      sectionKey={activeSection.key}
      initialData={profile}
      publicId={profile.public_id}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
    />
  {/snippet}
</SectionEditHarness>
