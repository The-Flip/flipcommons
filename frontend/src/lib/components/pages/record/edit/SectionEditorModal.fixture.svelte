<script lang="ts">
  import type { SaveMeta } from '$lib/components/editors/save-model-claims';
  import SectionEditorModal from './SectionEditorModal.svelte';

  let {
    showSwitcher = false,
    switcherDisabled = false,
  }: {
    showSwitcher?: boolean;
    switcherDisabled?: boolean;
  } = $props();

  let open = $state(false);
  let closeCount = $state(0);
  let saveCount = $state(0);
  let lastNote = $state('');
  let lastCitationId = $state('');
  let lastSwitched = $state('');

  function openModal() {
    open = true;
  }

  function closeModal() {
    closeCount++;
    open = false;
  }

  function saveModal(meta: SaveMeta) {
    saveCount++;
    lastNote = meta.note ?? '';
    lastCitationId = meta.citation ? String(meta.citation.citation_instance_id) : '';
    open = false;
  }

  const switcherItems = [
    { key: 'overview', label: 'Overview', onclick: () => (lastSwitched = 'overview') },
    {
      key: 'technology',
      label: 'Technology',
      onclick: () => (lastSwitched = 'technology'),
    },
  ];
</script>

<button type="button" onclick={openModal}>Open editor</button>

<SectionEditorModal
  heading="Overview"
  {open}
  switcherItems={showSwitcher ? switcherItems : []}
  currentSectionKey={showSwitcher ? 'overview' : undefined}
  {switcherDisabled}
  onclose={closeModal}
  onsave={saveModal}
>
  <label>
    Description
    <input type="text" value="Prototype content" />
  </label>
</SectionEditorModal>

<p data-testid="close-count">{closeCount}</p>
<p data-testid="save-count">{saveCount}</p>
<p data-testid="last-note">{lastNote}</p>
<p data-testid="last-citation">{lastCitationId}</p>
<p data-testid="last-switched">{lastSwitched}</p>
