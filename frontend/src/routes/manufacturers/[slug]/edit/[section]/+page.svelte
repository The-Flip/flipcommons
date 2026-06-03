<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { getEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import {
    defaultManufacturerSectionSegment,
    findManufacturerSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/manufacturer/manufacturer-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/entity/model/save-model-claims';
  import ManufacturerEditorSwitch from '../ManufacturerEditorSwitch.svelte';

  let { data } = $props();
  let manufacturer = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(
    sectionSegment ? findManufacturerSectionBySegment(sectionSegment) : undefined,
  );

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  let saveCounter = $state(0);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/manufacturers/${slug}/edit/${defaultManufacturerSectionSegment()}`), {
        replaceState: true,
      });
    }
  });

  async function handleSave(meta: SaveMeta) {
    editError = '';
    await editorRef?.save(meta);
  }

  function handleCancel() {
    if (editorRef?.isDirty() && !confirm('Discard unsaved changes?')) {
      return;
    }
    goto(resolve(`/manufacturers/${slug}`));
  }

  function handleSaved() {
    editLayout.setDirty(false);
    saveCounter++;
  }

  function handleDirtyChange(dirty: boolean) {
    editLayout.setDirty(dirty);
  }
</script>

{#if section}
  {#key `${section.key}:${saveCounter}`}
    <SectionEditorForm
      error={editError}
      showCitation={section.showCitation}
      showMixedEditWarning={section.showMixedEditWarning}
      oncancel={handleCancel}
      onsave={handleSave}
    >
      <ManufacturerEditorSwitch
        sectionKey={section.key}
        initialData={manufacturer}
        slug={manufacturer.slug}
        bind:editorRef
        onsaved={handleSaved}
        onerror={(msg) => (editError = msg)}
        ondirtychange={handleDirtyChange}
      />
    </SectionEditorForm>
  {/key}
{/if}
