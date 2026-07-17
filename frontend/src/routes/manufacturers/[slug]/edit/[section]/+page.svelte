<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditHarness from '$lib/components/pages/record/edit/SectionEditHarness.svelte';
  import {
    defaultManufacturerSectionSegment,
    findManufacturerSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/manufacturer/manufacturer-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import ManufacturerEditorSwitch from '../ManufacturerEditorSwitch.svelte';

  let { data } = $props();
  let manufacturer = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(
    sectionSegment ? findManufacturerSectionBySegment(sectionSegment) : undefined,
  );

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/manufacturers/${slug}/edit/${defaultManufacturerSectionSegment()}`), {
        replaceState: true,
      });
    }
  });
</script>

<SectionEditHarness {section} detailHref={`/manufacturers/${slug}`}>
  {#snippet editor({ ref, onsaved, onerror }, section)}
    <ManufacturerEditorSwitch
      sectionKey={section.key}
      initialData={manufacturer}
      slug={manufacturer.slug}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
    />
  {/snippet}
</SectionEditHarness>
