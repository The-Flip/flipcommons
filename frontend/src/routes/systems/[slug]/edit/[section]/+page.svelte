<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/editors/editor-contract';
  import { getEditLayoutContext } from '$lib/components/editors/edit-layout-context';
  import {
    defaultSystemSectionSegment,
    findSystemSectionBySegment,
  } from '$lib/components/editors/system-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { SaveMeta } from '../save-system-claims';
  import SystemEditorSwitch from '../SystemEditorSwitch.svelte';

  let { data } = $props();
  let system = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(sectionSegment ? findSystemSectionBySegment(sectionSegment) : undefined);

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  let saveCounter = $state(0);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/systems/${slug}/edit/${defaultSystemSectionSegment()}`), {
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
    goto(resolve(`/systems/${slug}`));
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
      <SystemEditorSwitch
        sectionKey={section.key}
        initialData={system}
        slug={system.slug}
        bind:editorRef
        onsaved={handleSaved}
        onerror={(msg) => (editError = msg)}
        ondirtychange={handleDirtyChange}
      />
    </SectionEditorForm>
  {/key}
{/if}
