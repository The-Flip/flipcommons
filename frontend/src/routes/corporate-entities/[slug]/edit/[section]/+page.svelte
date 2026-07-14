<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditHarness from '$lib/components/pages/record/edit/SectionEditHarness.svelte';
  import {
    defaultCorporateEntitySectionSegment,
    findCorporateEntitySectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/corporate-entity/corporate-entity-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import CorporateEntityEditorSwitch from '../CorporateEntityEditorSwitch.svelte';

  let { data } = $props();
  let ce = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(
    sectionSegment ? findCorporateEntitySectionBySegment(sectionSegment) : undefined,
  );

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/corporate-entities/${slug}/edit/${defaultCorporateEntitySectionSegment()}`), {
        replaceState: true,
      });
    }
  });
</script>

<SectionEditHarness {section} detailHref={`/corporate-entities/${slug}`}>
  {#snippet editor({ ref, onsaved, onerror }, section)}
    <CorporateEntityEditorSwitch
      sectionKey={section.key}
      initialData={ce}
      slug={ce.slug}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
    />
  {/snippet}
</SectionEditHarness>
