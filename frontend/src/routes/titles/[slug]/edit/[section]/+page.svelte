<script lang="ts">
  import { page } from '$app/state';
  import { goto, invalidateAll } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import { getEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import TitleEditorSwitch from '../TitleEditorSwitch.svelte';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/save-claims-shared';
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

  $effect(() => {
    if (!sectionAvailable) {
      goto(resolve(`/titles/${slug}/edit/${defaultTitleSectionSegment(isSingleModel)}`), {
        replaceState: true,
      });
    }
  });

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  let saveCounter = $state(0);

  // Single reactive dirty read: gates the footer Save button and the section
  // nav-lock, and guards cancel. `false` while the editor is unmounted keeps
  // Save disabled — the safe default.
  let editorDirty = $derived(editorRef?.dirty ?? false);

  $effect(() => {
    editLayout.setDirty(editorDirty);
  });

  async function handleSave(meta: SaveMeta) {
    editError = '';
    await editorRef?.save(meta);
  }

  function handleCancel() {
    if (editorDirty && !confirm('Discard unsaved changes?')) {
      return;
    }
    goto(resolve(`/titles/${slug}`));
  }

  async function handleSaved() {
    await invalidateAll();
    const updatedSlug = data.profile.slug;
    if (updatedSlug !== slug) {
      await goto(resolve(`/titles/${updatedSlug}/edit/${sectionSegment}`), {
        replaceState: true,
      });
    }
    saveCounter++;
  }
</script>

{#if section && sectionAvailable}
  {#key saveCounter}
    <SectionEditorForm
      error={editError}
      showCitation={section.showCitation}
      showMixedEditWarning={section.showMixedEditWarning}
      dirty={editorDirty}
      oncancel={handleCancel}
      onsave={handleSave}
    >
      <TitleEditorSwitch
        sectionKey={section.key}
        initialData={title}
        slug={title.slug}
        bind:editorRef
        onsaved={handleSaved}
        onerror={(msg: string) => (editError = msg)}
      />
    </SectionEditorForm>
  {/key}
{/if}
