<script lang="ts" generics="TKey extends string">
  import type { Snippet } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolveHref } from '$lib/utils';
  import Button from '$lib/components/ui/Button.svelte';
  import SectionEditorForm from './SectionEditorForm.svelte';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import type { SectionEditorHandle } from '$lib/components/editors/editor-contract';
  import type { EditSectionDef } from '$lib/components/editors/edit-section-def';
  import { getEditLayoutContext } from '$lib/components/editors/edit-layout-context';
  import type { SaveMeta } from '$lib/components/editors/save-claims-shared';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';

  type SectionDef = EditSectionDef<TKey> & { usesSectionEditorForm: boolean };
  type EditorRefBox = { current: SectionEditorHandle | undefined };
  type EditorCallbacks = {
    ref: EditorRefBox;
    onsaved: () => void;
    onerror: (msg: string) => void;
    ondirtychange: (dirty: boolean) => void;
  };

  let {
    basePath,
    sections,
    defaultSegment,
    editor,
    immediateEditor,
  }: {
    basePath: string;
    sections: SectionDef[];
    defaultSegment: string;
    editor: Snippet<[TKey, EditorCallbacks]>;
    /**
     * Optional renderer for sections declared with `usesSectionEditorForm: false`
     * (e.g. the media modal). Invoked on the mobile route for those sections
     * instead of wrapping in SectionEditorForm; the caller owns the full content
     * and a Done button is appended to return to the detail page.
     */
    immediateEditor?: Snippet;
  } = $props();

  let slug = $derived(page.params.slug);
  let sectionSegment = $derived(page.params.section);
  let section = $derived(
    sectionSegment ? sections.find((s) => s.segment === sectionSegment) : undefined,
  );

  const editLayout = getEditLayoutContext();

  let editorRef = $state<SectionEditorHandle>();
  let editError = $state('');
  let saveCounter = $state(0);
  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT, null);
  let isMobile = $derived(isMobileFlag.current);

  $effect(() => {
    if (isMobile === true && !section) {
      goto(resolveHref(`${basePath}/${slug}/edit/${defaultSegment}`), {
        replaceState: true,
      });
    }
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
    if (editorRef?.isDirty() && !confirm('Discard unsaved changes?')) {
      return;
    }
    goto(resolveHref(`${basePath}/${slug}`));
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
        {@render editor(section.key, {
          ref: refBox,
          onsaved: handleSaved,
          onerror: (msg) => (editError = msg),
          ondirtychange: handleDirtyChange,
        })}
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
