<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/editors/editor-contract';
  import { getEditLayoutContext } from '$lib/components/editors/edit-layout-context';
  import {
    defaultCorporateEntitySectionSegment,
    findCorporateEntitySectionBySegment,
  } from '$lib/components/editors/corporate-entity-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { SaveMeta } from '$lib/components/editors/save-claims-shared';
  import CorporateEntityEditorSwitch from '../CorporateEntityEditorSwitch.svelte';

  let { data } = $props();
  let ce = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(
    sectionSegment ? findCorporateEntitySectionBySegment(sectionSegment) : undefined,
  );

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  let saveCounter = $state(0);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/corporate-entities/${slug}/edit/${defaultCorporateEntitySectionSegment()}`), {
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
    goto(resolve(`/corporate-entities/${slug}`));
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
      <CorporateEntityEditorSwitch
        sectionKey={section.key}
        initialData={ce}
        slug={ce.slug}
        bind:editorRef
        onsaved={handleSaved}
        onerror={(msg) => (editError = msg)}
        ondirtychange={handleDirtyChange}
      />
    </SectionEditorForm>
  {/key}
{/if}
