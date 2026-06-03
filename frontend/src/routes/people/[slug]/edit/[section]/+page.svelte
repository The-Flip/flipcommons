<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import Button from '$lib/components/ui/Button.svelte';
  import SectionEditorForm from '$lib/components/pages/record/edit/SectionEditorForm.svelte';
  import MediaEditor from '$lib/components/pages/record/edit/editors/MediaEditor.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { getEditLayoutContext } from '$lib/components/pages/record/edit/editors/edit-layout-context';
  import {
    defaultPersonSectionSegment,
    findPersonSectionBySegment,
  } from '$lib/components/pages/record/edit/editors/entity/person/person-edit-sections';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { SaveMeta } from '../save-person-claims';
  import PersonEditorSwitch from '../PersonEditorSwitch.svelte';

  let { data } = $props();
  let person = $derived(data.profile);
  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(sectionSegment ? findPersonSectionBySegment(sectionSegment) : undefined);

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  let saveCounter = $state(0);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolve(`/people/${slug}/edit/${defaultPersonSectionSegment()}`), {
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
    goto(resolve(`/people/${slug}`));
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
  {#if section.usesSectionEditorForm}
    {#key `${section.key}:${saveCounter}`}
      <SectionEditorForm
        error={editError}
        showCitation={section.showCitation}
        showMixedEditWarning={section.showMixedEditWarning}
        oncancel={handleCancel}
        onsave={handleSave}
      >
        <PersonEditorSwitch
          sectionKey={section.key}
          initialData={person}
          slug={person.slug}
          bind:editorRef
          onsaved={handleSaved}
          onerror={(msg) => (editError = msg)}
          ondirtychange={handleDirtyChange}
        />
      </SectionEditorForm>
    {/key}
  {:else if section.key === 'media'}
    <MediaEditor entityType="person" slug={person.slug} media={person.uploaded_media} />
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
