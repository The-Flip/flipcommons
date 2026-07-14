<!--
@component
The one host for a full-page section edit. Owns the whole editor lifecycle and
footer chrome so route pages don't re-implement it: it holds the editor handle,
derives the single reactive `editorDirty` from `editorRef.dirty` (gating the
footer Save button, the section nav-lock and the cancel guard), commits saves,
toasts, and remounts the editor on save so it re-captures fresh initial data.

Callers stay thin: resolve which `section` is active (and any entity redirects),
then hand over the editor-switch snippet, a `detailHref` to exit to, and — only
when a save can change the URL or needs a reload — an `onsaved` hook. Sections
declared `usesSectionEditorForm: false` render through `immediateEditor` with a
Done button instead of the Save/Cancel form.
-->
<script lang="ts" generics="TSection extends HarnessSection">
  import type { Snippet } from 'svelte';
  import { goto } from '$app/navigation';
  import { resolveHref } from '$lib/utils';
  import Button from '$lib/components/ui/Button.svelte';
  import SectionEditorForm from './SectionEditorForm.svelte';
  import { toast } from '$lib/toast/toast.svelte';
  import type { SectionEditorHandle } from './editors/editor-contract';
  import type { EditorCallbacks, EditorRefBox, HarnessSection } from './editors/editor-callbacks';
  import { getEditLayoutContext } from './editors/edit-layout-context';
  import type { SaveMeta } from './editors/save-claims-shared';

  let {
    section,
    detailHref,
    onsaved,
    editor,
    immediateEditor,
  }: {
    /** The resolved active section; the harness renders nothing when undefined. */
    section: TSection | undefined;
    /** Where Cancel and Done navigate to (the record's detail page). */
    detailHref: string;
    /**
     * Optional post-save hook, awaited after the "Saved." toast and before the
     * editor remounts. Use it for `invalidateAll()` and any slug-change redirect;
     * omit it when a plain in-place refresh is enough.
     */
    onsaved?: () => void | Promise<void>;
    /**
     * Renders the entity editor switch. Receives the wiring (bind via
     * `callbacks.ref.current`) and the narrowed active `section`.
     */
    editor: Snippet<[EditorCallbacks, TSection]>;
    /**
     * Renderer for `usesSectionEditorForm: false` sections (e.g. media): the
     * caller owns the body and a Done button is appended to return to detail.
     */
    immediateEditor?: Snippet;
  } = $props();

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  // Bump on each successful save so the editor block remounts and re-captures
  // fresh initial data — the editor snapshots `original` once at mount, so
  // without a remount the dirty comparison stays frozen against pre-save values.
  let saveCounter = $state(0);

  // Single reactive dirty read: gates the footer Save button and the section
  // nav-lock, and guards cancel. `false` while the editor is unmounted (between
  // remounts, or on an immediate section) keeps Save disabled — the safe default.
  let editorDirty = $derived(editorRef?.dirty ?? false);

  $effect(() => {
    editLayout.setDirty(editorDirty);
  });

  const refBox: EditorRefBox = {
    get current() {
      return editorRef;
    },
    set current(v) {
      editorRef = v;
    },
  };

  async function handleSave(meta: SaveMeta) {
    editError = '';
    await editorRef?.save(meta);
  }

  function handleCancel() {
    if (editorDirty && !confirm('Discard unsaved changes?')) {
      return;
    }
    goto(resolveHref(detailHref));
  }

  async function handleSaved() {
    // Toast immediately after the click, matching the desktop modal; keep it a
    // terse "Saved." rather than repeating the section name.
    toast.success('Saved.');
    await onsaved?.();
    saveCounter++;
  }
</script>

{#if section}
  {#if section.usesSectionEditorForm}
    {#key `${section.key}:${saveCounter}`}
      <SectionEditorForm
        error={editError}
        showCitation={section.showCitation}
        showMixedEditWarning={section.showMixedEditWarning}
        dirty={editorDirty}
        oncancel={handleCancel}
        onsave={handleSave}
      >
        {@render editor(
          { ref: refBox, onsaved: handleSaved, onerror: (msg) => (editError = msg) },
          section,
        )}
      </SectionEditorForm>
    {/key}
  {:else if immediateEditor}
    {@render immediateEditor()}
    <div class="immediate-footer">
      <Button onclick={handleCancel}>Done</Button>
    </div>
  {/if}
{/if}

<style>
  .immediate-footer {
    display: flex;
    justify-content: flex-end;
    margin-top: var(--size-4);
  }
</style>
