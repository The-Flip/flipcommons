<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditHarness from '$lib/components/pages/record/edit/SectionEditHarness.svelte';
  import MediaEditor from '$lib/components/pages/record/edit/editors/MediaEditor.svelte';
  import {
    defaultPersonSectionSegment,
    findPersonSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/person/person-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import PersonEditorSwitch from '../PersonEditorSwitch.svelte';

  let { data } = $props();
  let person = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(sectionSegment ? findPersonSectionBySegment(sectionSegment) : undefined);

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/people/${slug}/edit/${defaultPersonSectionSegment()}`), {
        replaceState: true,
      });
    }
  });
</script>

<SectionEditHarness {section} detailHref={`/people/${slug}`}>
  {#snippet editor({ ref, onsaved, onerror }, section)}
    <PersonEditorSwitch
      sectionKey={section.key}
      initialData={person}
      slug={person.slug}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
    />
  {/snippet}
  {#snippet immediateEditor()}
    <MediaEditor entityType="person" slug={person.slug} media={person.uploaded_media} />
  {/snippet}
</SectionEditHarness>
