<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { getEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import {
    defaultLocationSectionSegment,
    findLocationSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/location/location-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/save-claims-shared';
  import type { LocationDetailSchema } from '$lib/api/schema';
  import LocationEditorSwitch from '../LocationEditorSwitch.svelte';

  let { data } = $props();
  let profile = $derived<LocationDetailSchema>(data.profile);
  let path = $derived(page.params.path);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(sectionSegment ? findLocationSectionBySegment(sectionSegment) : undefined);
  let sectionAvailable = $derived(
    section !== undefined && (!section.countryOnly || profile.location_type === 'country'),
  );

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
    if (isMobile === true && !sectionAvailable) {
      goto(resolve(`/locations/${path}/edit/${defaultLocationSectionSegment()}`), {
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
    goto(resolve(`/locations/${path}`));
  }

  function handleSaved() {
    saveCounter++;
  }
</script>

{#if section && sectionAvailable}
  {#key `${section.key}:${saveCounter}`}
    <SectionEditorForm
      error={editError}
      showCitation={section.showCitation}
      showMixedEditWarning={section.showMixedEditWarning}
      dirty={editorDirty}
      oncancel={handleCancel}
      onsave={handleSave}
    >
      <LocationEditorSwitch
        sectionKey={section.key}
        initialData={profile}
        publicId={profile.public_id}
        bind:editorRef
        onsaved={handleSaved}
        onerror={(msg) => (editError = msg)}
      />
    </SectionEditorForm>
  {/key}
{/if}
