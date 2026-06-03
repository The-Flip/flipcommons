<script lang="ts">
  import { page } from '$app/state';
  import { goto, invalidateAll } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import MediaEditor from '$lib/components/pages/record/edit/editors/MediaEditor.svelte';
  import ModelEditorSwitch from '$lib/components/pages/record/edit/editors/entity/model/ModelEditorSwitch.svelte';
  import { getEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/entity/model/save-model-claims';
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

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  // Bump on each successful save so the editor block remounts with fresh
  // initialModel — the editor captures `original` once at mount, so without
  // a remount the dirty comparison stays frozen against pre-save values.
  let saveCounter = $state(0);

  async function handleSave(meta: SaveMeta) {
    editError = '';
    await editorRef?.save(meta);
  }

  function handleCancel() {
    if (editorRef?.isDirty() && !confirm('Discard unsaved changes?')) {
      return;
    }
    goto(resolve(`/models/${slug}`));
  }

  async function handleSaved() {
    editLayout.setDirty(false);
    await invalidateAll();
    // BasicsEditor can change the slug — redirect if needed
    const updatedSlug = data.profile.slug;
    if (updatedSlug !== slug) {
      await goto(resolve(`/models/${updatedSlug}/edit/${sectionSegment}`), {
        replaceState: true,
      });
    }
    saveCounter++;
  }

  function handleDirtyChange(dirty: boolean) {
    editLayout.setDirty(dirty);
  }
</script>

{#if section}
  {#if section.usesSectionEditorForm}
    {#key saveCounter}
      <SectionEditorForm
        error={editError}
        showCitation={section.showCitation}
        showMixedEditWarning={section.showMixedEditWarning}
        oncancel={handleCancel}
        onsave={handleSave}
      >
        <ModelEditorSwitch
          sectionKey={section.key}
          initialData={model}
          slug={model.slug}
          slim={slimBasics}
          bind:editorRef
          onsaved={handleSaved}
          onerror={(msg: string) => (editError = msg)}
          ondirtychange={handleDirtyChange}
        />
      </SectionEditorForm>
    {/key}
  {:else if section.key === 'media'}
    <MediaEditor entityType="model" slug={model.slug} media={model.uploaded_media} />
    <div class="media-footer">
      <Button onclick={handleCancel}>Done</Button>
    </div>
  {/if}
{/if}

<style>
  .media-footer {
    display: flex;
    justify-content: flex-end;
    margin-top: var(--size-4);
  }
</style>
