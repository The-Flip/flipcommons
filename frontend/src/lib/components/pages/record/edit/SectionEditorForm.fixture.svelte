<script lang="ts">
  import type { SaveMeta } from '$lib/components/editors/save-model-claims';
  import SectionEditorForm from './SectionEditorForm.svelte';

  let {
    showCitation = true,
    error = '',
  }: {
    showCitation?: boolean;
    error?: string;
  } = $props();

  let cancelCount = $state(0);
  let saveCount = $state(0);
  let lastNote = $state('');
  let lastCitationId = $state('');

  function handleCancel() {
    cancelCount++;
  }

  function handleSave(meta: SaveMeta) {
    saveCount++;
    lastNote = meta.note ?? '';
    lastCitationId = meta.citation ? String(meta.citation.citation_instance_id) : '';
  }
</script>

<SectionEditorForm {error} {showCitation} oncancel={handleCancel} onsave={handleSave}>
  <label>
    Description
    <input type="text" value="Prototype content" />
  </label>
</SectionEditorForm>

<p data-testid="cancel-count">{cancelCount}</p>
<p data-testid="save-count">{saveCount}</p>
<p data-testid="last-note">{lastNote}</p>
<p data-testid="last-citation">{lastCitationId}</p>
