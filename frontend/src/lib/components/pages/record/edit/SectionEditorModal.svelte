<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/entity/model/save-model-claims';
  import EditSectionMenu from '$lib/components/layout/page/EditSectionMenu.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import Modal from '$lib/components/ui/modal/Modal.svelte';
  import SectionEditorForm from './SectionEditorForm.svelte';

  let {
    heading,
    open,
    error = '',
    showCitation = true,
    showMixedEditWarning = false,
    switcherItems = [],
    currentSectionKey = undefined,
    switcherDisabled = false,
    onclose,
    onsave,
    children,
  }: {
    heading: string;
    open: boolean;
    error?: string;
    showCitation?: boolean;
    showMixedEditWarning?: boolean;
    switcherItems?: EditSectionMenuItem[];
    currentSectionKey?: string;
    switcherDisabled?: boolean;
    onclose: () => void;
    onsave: (meta: SaveMeta) => void;
    children: Snippet;
  } = $props();

  let formRef: SectionEditorForm | undefined = $state();

  // Reset note/citation state when the modal opens
  $effect(() => {
    if (open) {
      formRef?.resetMeta();
    }
  });

  function close() {
    onclose();
  }
</script>

<Modal title={switcherItems.length > 0 ? heading : `Edit ${heading}`} {open} onclose={close}>
  {#snippet titleContent()}
    {#if switcherItems.length > 0}
      <EditSectionMenu
        items={switcherItems}
        currentKey={currentSectionKey}
        disabled={switcherDisabled}
        variant="heading"
      />
    {:else}
      Edit {heading}
    {/if}
  {/snippet}
  <SectionEditorForm
    bind:this={formRef}
    {error}
    {showCitation}
    {showMixedEditWarning}
    oncancel={close}
    {onsave}
  >
    {@render children()}
  </SectionEditorForm>
</Modal>
