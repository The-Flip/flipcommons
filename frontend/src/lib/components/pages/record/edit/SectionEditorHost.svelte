<script lang="ts" generics="TSectionKey extends string">
  import type { Snippet } from 'svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import EditSectionMenu from '$lib/components/layout/page/EditSectionMenu.svelte';
  import Modal from '$lib/components/ui/modal/Modal.svelte';
  import SectionEditorModal from './SectionEditorModal.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type {
    EditorCallbacks,
    EditorRefBox,
  } from '$lib/components/pages/record/edit/editors/editor-callbacks';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/save-claims-shared';
  import { toast } from '$lib/toast/toast.svelte';

  type SectionDef = {
    key: TSectionKey;
    label: string;
    showCitation: boolean;
    showMixedEditWarning: boolean;
    usesSectionEditorForm: boolean;
  };

  let {
    editingKey = $bindable(),
    sections,
    switcherItems,
    editor,
    immediateEditor,
  }: {
    editingKey: TSectionKey | null;
    sections: SectionDef[];
    switcherItems: EditSectionMenuItem[];
    editor: Snippet<[TSectionKey, EditorCallbacks]>;
    immediateEditor?: Snippet;
  } = $props();

  let editError = $state('');
  let activeEditorRef: SectionEditorHandle | undefined = $state();

  // Single reactive dirty read for the active editor: gates the footer Save
  // button and the section switcher, and guards Escape/backdrop dismissal.
  // `false` while no editor is mounted — the safe default.
  let editorDirty = $derived(activeEditorRef?.dirty ?? false);

  const refBox: EditorRefBox = {
    get current() {
      return activeEditorRef;
    },
    set current(v) {
      activeEditorRef = v;
    },
  };

  const callbacks: EditorCallbacks = {
    ref: refBox,
    onsaved: () => {
      // The toast appears immediately after the user clicked Save, so
      // a short "Saved." is less noisy than repeating the section name.
      toast.success('Saved.');
      clearEditorState();
    },
    onerror: (msg) => (editError = msg),
  };

  function clearEditorState() {
    editingKey = null;
    editError = '';
  }

  // Guard Escape/backdrop dismissal from silently discarding edits.
  // The switcher is disabled while dirty; the explicit Cancel button
  // inside the form goes through SectionEditorForm and skips this path.
  function closeEditor() {
    if (editorDirty && !confirm('Discard unsaved changes?')) {
      return;
    }
    clearEditorState();
  }

  async function saveCurrentSection(meta: SaveMeta) {
    editError = '';
    await activeEditorRef?.save(meta);
  }

  let currentSection = $derived(sections.find((s) => s.key === editingKey));
  let currentFormSection = $derived(
    currentSection?.usesSectionEditorForm ? currentSection : undefined,
  );
  let immediateActive = $derived(!!currentSection && !currentSection.usesSectionEditorForm);
</script>

{#if currentFormSection}
  {#key currentFormSection.key}
    <SectionEditorModal
      heading={currentFormSection.label}
      open={true}
      error={editError}
      showCitation={currentFormSection.showCitation}
      showMixedEditWarning={currentFormSection.showMixedEditWarning}
      {switcherItems}
      currentSectionKey={currentFormSection.key}
      switcherDisabled={editorDirty}
      dirty={editorDirty}
      onclose={closeEditor}
      onsave={saveCurrentSection}
    >
      {@render editor(currentFormSection.key, callbacks)}
    </SectionEditorModal>
  {/key}
{/if}

{#if immediateEditor && currentSection}
  {@const section = currentSection}
  <Modal title={section.label} open={immediateActive} onclose={closeEditor}>
    {#snippet titleContent()}
      <EditSectionMenu items={switcherItems} currentKey={section.key} variant="heading" />
    {/snippet}
    {#snippet footer()}
      <Button onclick={closeEditor}>Done</Button>
    {/snippet}
    {@render immediateEditor()}
  </Modal>
{/if}
