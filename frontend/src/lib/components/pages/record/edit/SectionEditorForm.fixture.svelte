<script lang="ts">
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/entity/model/save-model-claims';
  import SectionEditorForm from './SectionEditorForm.svelte';

  let {
    showCitation = true,
    error = '',
    dirty = true,
  }: {
    showCitation?: boolean;
    error?: string;
    dirty?: boolean;
  } = $props();

  let cancelCount = $state(0);
  let saveCount = $state(0);
  let lastNote = $state('');
  let lastCitationSourceId = $state('');

  function handleCancel() {
    cancelCount++;
  }

  function handleSave(meta: SaveMeta) {
    saveCount++;
    lastNote = meta.note ?? '';
    lastCitationSourceId = meta.citations?.length
      ? String(meta.citations[0].citation_source_id)
      : '';
  }
</script>

<SectionEditorForm {error} {showCitation} {dirty} oncancel={handleCancel} onsave={handleSave}>
  <label>
    Description
    <input type="text" value="Prototype content" />
  </label>
</SectionEditorForm>

<p data-testid="cancel-count">{cancelCount}</p>
<p data-testid="save-count">{saveCount}</p>
<p data-testid="last-note">{lastNote}</p>
<p data-testid="last-citation">{lastCitationSourceId}</p>
