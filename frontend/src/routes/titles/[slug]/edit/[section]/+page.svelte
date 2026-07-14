<script lang="ts">
  import { page } from '$app/state';
  import { goto, invalidateAll } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditHarness from '$lib/components/pages/record/edit/SectionEditHarness.svelte';
  import TitleEditorSwitch from '../TitleEditorSwitch.svelte';
  import {
    defaultTitleSectionSegment,
    findTitleSectionBySegment,
    titleSectionsFor,
  } from '$lib/components/pages/record/edit/editors/entity/title/title-edit-sections';

  let { data } = $props();
  let title = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let isSingleModel = $derived(!!title.model_detail);
  let section = $derived(sectionSegment ? findTitleSectionBySegment(sectionSegment) : undefined);
  let sectionAvailable = $derived(
    section ? titleSectionsFor(isSingleModel).some((s) => s.key === section!.key) : false,
  );
  let activeSection = $derived(section && sectionAvailable ? section : undefined);

  $effect(() => {
    if (!sectionAvailable) {
      goto(resolve(`/titles/${slug}/edit/${defaultTitleSectionSegment(isSingleModel)}`), {
        replaceState: true,
      });
    }
  });

  async function handleSaved() {
    await invalidateAll();
    const updatedSlug = data.profile.slug;
    if (updatedSlug !== slug) {
      await goto(resolve(`/titles/${updatedSlug}/edit/${sectionSegment}`), {
        replaceState: true,
      });
    }
  }
</script>

<SectionEditHarness section={activeSection} detailHref={`/titles/${slug}`} onsaved={handleSaved}>
  {#snippet editor({ ref, onsaved, onerror }, activeSection)}
    <TitleEditorSwitch
      sectionKey={activeSection.key}
      initialData={title}
      slug={title.slug}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
    />
  {/snippet}
</SectionEditHarness>
