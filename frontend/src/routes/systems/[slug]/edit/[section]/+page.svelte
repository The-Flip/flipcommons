<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditHarness from '$lib/components/pages/record/edit/SectionEditHarness.svelte';
  import {
    defaultSystemSectionSegment,
    findSystemSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/system/system-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import SystemEditorSwitch from '../SystemEditorSwitch.svelte';

  let { data } = $props();
  let system = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(sectionSegment ? findSystemSectionBySegment(sectionSegment) : undefined);

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/systems/${slug}/edit/${defaultSystemSectionSegment()}`), {
        replaceState: true,
      });
    }
  });
</script>

<SectionEditHarness {section} detailHref={`/systems/${slug}`}>
  {#snippet editor({ ref, onsaved, onerror }, section)}
    <SystemEditorSwitch
      sectionKey={section.key}
      initialData={system}
      slug={system.slug}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
    />
  {/snippet}
</SectionEditHarness>
