<!-- @component The "Evidence for this edit" panel: a stacked list of citations,
  each refinable (locator, quote) until save. Rows are the shared
  CitationInstanceFields body; "Add citation" opens the picker and appends —
  multiple separate sources backing one edit are first-class. -->
<script lang="ts">
  import { type EditCitationSelection } from '$lib/edit-citation';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';
  import CitationAutocomplete from './CitationAutocomplete.svelte';
  import CitationInstanceFields from './CitationInstanceFields.svelte';
  import type { CompletedCitationDraft } from './citation-types';

  let {
    citations = $bindable<EditCitationSelection[]>([]),
    showMixedEditWarning = false,
  }: {
    citations?: EditCitationSelection[];
    showMixedEditWarning?: boolean;
  } = $props();

  let pickerOpen = $state(false);

  // The picker hands back a content spec, not a minted instance — the spec
  // rides the save payload and the backend mints the shared instances then.
  // The list updates by reassignment (not push/splice) so the change reaches
  // the parent's binding regardless of how deep its reactivity goes.
  function handleComplete(draft: CompletedCitationDraft) {
    citations = [
      ...citations,
      {
        citationSourceId: draft.sourceId,
        sourceName: draft.sourceName,
        sourceType: draft.sourceType,
        locator: draft.locator,
        quote: '',
      },
    ];
    pickerOpen = false;
  }

  function removeCitation(index: number) {
    citations = citations.filter((_, i) => i !== index);
  }

  function openPicker() {
    pickerOpen = true;
  }

  function closePicker() {
    pickerOpen = false;
  }
</script>

<FieldGroup label="Evidence for this edit" optional>
  <!-- eslint-disable-next-line @typescript-eslint/no-unused-vars -->
  {#snippet children(inputId, errorId)}
    <div class="citation-field" id={inputId}>
      {#each citations as citation, index (citation)}
        <CitationInstanceFields {citation} onremove={() => removeCitation(index)} />
      {/each}

      <!-- The picker replaces the button that summoned it (the same swap as
           the "Add a locator" reveal): while it's open, the picker IS the
           add-citation action, so a lingering button would be a dead control. -->
      {#if pickerOpen}
        <div class="citation-picker">
          <CitationAutocomplete
            oncomplete={handleComplete}
            oncancel={closePicker}
            onback={closePicker}
          />
        </div>
      {:else}
        <div class="citation-actions">
          <button type="button" class="citation-button" onclick={openPicker}>
            {citations.length > 0 ? 'Add another citation' : 'Add citation'}
          </button>
        </div>
      {/if}

      {#if showMixedEditWarning && citations.length > 0}
        <p class="citation-warning">
          {citations.length === 1 ? 'This citation' : 'These citations'} will apply to all changed fields
          in this save. Split unrelated edits if needed.
        </p>
      {/if}
    </div>
  {/snippet}
</FieldGroup>

<style>
  .citation-field {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .citation-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-2);
  }

  .citation-button {
    padding: var(--size-1) var(--size-3);
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
    background: var(--color-input-bg);
    color: var(--color-text);
    font: inherit;
    cursor: pointer;
  }

  .citation-warning {
    margin: 0;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .citation-picker {
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background: var(--color-surface);
    overflow: hidden;
  }
</style>
