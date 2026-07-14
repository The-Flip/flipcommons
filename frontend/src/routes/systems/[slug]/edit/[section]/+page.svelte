<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { getEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import {
    defaultSystemSectionSegment,
    findSystemSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/system/system-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/entity/system/save-system-claims';
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

  // Single reactive dirty read: gates the footer Save button and the section
  // nav-lock, and guards cancel. `false` while the editor is unmounted keeps
  // Save disabled — the safe default.
  let editorDirty = $derived(editorRef?.dirty ?? false);

  $effect(() => {
    editLayout.setDirty(editorDirty);
  });
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
    if (editorDirty && !confirm('Discard unsaved changes?')) {
      return;
    }
    goto(resolve(`/systems/${slug}`));
  }

  function handleSaved() {
    saveCounter++;
  }
</script>

{#if section}
  {#key `${section.key}:${saveCounter}`}
    <SectionEditorForm
      error={editError}
      showCitation={section.showCitation}
      showMixedEditWarning={section.showMixedEditWarning}
      dirty={editorDirty}
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
      />
    </SectionEditorForm>
  {/key}
{/if}
