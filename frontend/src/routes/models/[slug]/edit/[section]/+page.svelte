<script lang="ts">
  import { page } from '$app/state';
  import { goto, invalidateAll } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditHarness from '$lib/components/pages/record/edit/SectionEditHarness.svelte';
  import MediaEditor from '$lib/components/pages/record/edit/editors/MediaEditor.svelte';
  import ModelEditorSwitch from '$lib/components/pages/record/edit/editors/entity/model/ModelEditorSwitch.svelte';
  import { findSectionBySegment } from '$lib/components/pages/record/edit/editors/entity/model/model-edit-sections';
  import { modelHasTitleOwnedIdentity } from '$lib/catalog-rules';

  let { data } = $props();
  let model = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(sectionSegment ? findSectionBySegment(sectionSegment) : undefined);

  // On single-model titles the model's title is fixed — the Title picker in
  // Basics must not be re-assignable. Name/slug/abbreviations are handled
  // separately: the Name section is filtered out of the switcher and this
  // page redirects when the URL targets a hidden section.
  let slimBasics = $derived(modelHasTitleOwnedIdentity(model));

  // Redirect invalid or hidden sections to basics. A section may be hidden when
  // the model's identity is title-owned (e.g. Name on single-model titles).
  $effect(() => {
    const hidden = section?.hideOnTitleOwnedIdentity && modelHasTitleOwnedIdentity(model);
    if (!section || hidden) {
      goto(resolve(`/models/${slug}/edit/basics`), { replaceState: true });
    }
  });

  async function handleSaved() {
    await invalidateAll();
    // BasicsEditor can change the slug — redirect if needed
    const updatedSlug = data.profile.slug;
    if (updatedSlug !== slug) {
      await goto(resolve(`/models/${updatedSlug}/edit/${sectionSegment}`), {
        replaceState: true,
      });
    }
  }
</script>

<SectionEditHarness {section} detailHref={`/models/${slug}`} onsaved={handleSaved}>
  {#snippet editor({ ref, onsaved, onerror }, section)}
    <ModelEditorSwitch
      sectionKey={section.key}
      initialData={model}
      slug={model.slug}
      slim={slimBasics}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
    />
  {/snippet}
  {#snippet immediateEditor()}
    <MediaEditor entityType="model" slug={model.slug} media={model.uploaded_media} />
  {/snippet}
</SectionEditHarness>
