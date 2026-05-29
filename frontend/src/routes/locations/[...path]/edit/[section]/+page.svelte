<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import SectionEditorForm from '$lib/components/SectionEditorForm.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/editors/editor-contract';
  import { getEditLayoutContext } from '$lib/components/editors/edit-layout-context';
  import {
    defaultLocationSectionSegment,
    findLocationSectionBySegment,
  } from '$lib/components/editors/location-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { SaveMeta } from '$lib/components/editors/save-claims-shared';
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
    if (editorRef?.isDirty() && !confirm('Discard unsaved changes?')) {
      return;
    }
    goto(resolve(`/locations/${path}`));
  }

  function handleSaved() {
    editLayout.setDirty(false);
    saveCounter++;
  }

  function handleDirtyChange(dirty: boolean) {
    editLayout.setDirty(dirty);
  }
</script>

{#if section && sectionAvailable}
  {#key `${section.key}:${saveCounter}`}
    <SectionEditorForm
      error={editError}
      showCitation={section.showCitation}
      showMixedEditWarning={section.showMixedEditWarning}
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
        ondirtychange={handleDirtyChange}
      />
    </SectionEditorForm>
  {/key}
{/if}
