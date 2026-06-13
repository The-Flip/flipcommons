<script lang="ts">
  import type { CitationInstanceSchema } from '$lib/api/schema';
  import { type EditCitationSelection } from '$lib/edit-citation';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';
  import CitationAutocomplete from './CitationAutocomplete.svelte';

  let {
    citation = $bindable<EditCitationSelection | null>(null),
    showMixedEditWarning = false,
  }: {
    citation?: EditCitationSelection | null;
    showMixedEditWarning?: boolean;
  } = $props();

  let pickerOpen = $state(false);

  function formatCitationSummary(selectedCitation: EditCitationSelection): string {
    return selectedCitation.locator
      ? `${selectedCitation.sourceName}, ${selectedCitation.locator}`
      : selectedCitation.sourceName;
  }

  // The instance is already minted by CitationAutocomplete; read its fields
  // directly — no pk-keyed refetch. Mint failures surface inside the picker.
  function handleComplete(instance: CitationInstanceSchema) {
    citation = {
      citationInstanceId: instance.id,
      sourceName: instance.citation_source_name,
      locator: instance.locator,
    };
    pickerOpen = false;
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
    <div class="citation-field">
      {#if citation}
        <div id={inputId} class="citation-summary">
          {formatCitationSummary(citation)}
        </div>
      {/if}

      <div class="citation-actions">
        <button type="button" class="citation-button" onclick={openPicker}>
          {citation ? 'Change citation' : 'Add citation'}
        </button>
        {#if citation}
          <button
            type="button"
            class="citation-button citation-button-secondary"
            onclick={() => (citation = null)}
          >
            Remove citation
          </button>
        {/if}
      </div>

      {#if showMixedEditWarning && citation}
        <p class="citation-warning">
          This citation will apply to all changed fields in this save. Split unrelated edits if
          needed.
        </p>
      {/if}

      {#if pickerOpen}
        <div class="citation-picker">
          <CitationAutocomplete
            oncomplete={handleComplete}
            oncancel={closePicker}
            onback={closePicker}
          />
        </div>
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

  .citation-summary {
    padding: var(--size-2) var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background: var(--color-surface);
    color: var(--color-text);
    font-size: var(--font-size-1);
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

  .citation-button-secondary {
    color: var(--color-text-muted);
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
