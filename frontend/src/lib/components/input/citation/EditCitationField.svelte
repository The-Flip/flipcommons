<!-- @component The "Evidence for this edit" panel: pick a citation, then refine its locator and quote until save. -->
<script lang="ts">
  import { tick } from 'svelte';
  import { type EditCitationSelection } from '$lib/edit-citation';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';
  import CitationAutocomplete from './CitationAutocomplete.svelte';
  import type { CompletedCitationDraft } from './citation-types';

  let {
    citation = $bindable<EditCitationSelection | null>(null),
    showMixedEditWarning = false,
  }: {
    citation?: EditCitationSelection | null;
    showMixedEditWarning?: boolean;
  } = $props();

  let pickerOpen = $state(false);

  // The locator is unprompted but reachable: nothing mints until save, so
  // this panel — not an extra picker stage — is where a skip_locator cite
  // picks up its rare locator (a video post's 1:35, an article's § heading).
  // The input stays visible once it has ever held text this session, so a
  // cleared value doesn't yank the field out from under the contributor.
  let locatorAdded = $state(false);
  let locatorInput: HTMLInputElement | undefined = $state();
  let locatorVisible = $derived(!!citation?.locator || locatorAdded);

  async function addLocator() {
    locatorAdded = true;
    await tick();
    locatorInput?.focus();
  }

  // The picker hands back a content spec, not a minted instance — the spec
  // rides the save payload and the backend mints the shared instance then.
  // A quote already typed survives a source re-pick: clearing user-entered
  // text on "Change citation" would be worse than a stale quote the user can
  // see and edit.
  function handleComplete(draft: CompletedCitationDraft) {
    citation = {
      citationSourceId: draft.sourceId,
      sourceName: draft.sourceName,
      locator: draft.locator,
      quote: citation?.quote ?? '',
    };
    // Collapse back down for a fresh locator-less pick; a locator entered at
    // the picker's own stage (book/video) keeps the field open via `derived`.
    locatorAdded = false;
    pickerOpen = false;
  }

  function removeCitation() {
    citation = null;
    locatorAdded = false;
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
          {citation.sourceName}
        </div>
        {#if locatorVisible}
          <input
            bind:this={locatorInput}
            type="text"
            aria-label="Citation locator"
            placeholder="Where in the source (p. 42, 1:35)"
            maxlength="200"
            bind:value={citation.locator}
          />
        {/if}
        <textarea
          aria-label="Quote from the source"
          placeholder="Exact text quoted from the source"
          rows="3"
          maxlength="2000"
          bind:value={citation.quote}></textarea>
      {/if}

      <div class="citation-actions">
        <button type="button" class="citation-button" onclick={openPicker}>
          {citation ? 'Change citation' : 'Add citation'}
        </button>
        {#if citation && !locatorVisible}
          <button
            type="button"
            class="citation-button citation-button-secondary"
            onclick={addLocator}
          >
            Add a locator
          </button>
        {/if}
        {#if citation}
          <button
            type="button"
            class="citation-button citation-button-secondary"
            onclick={removeCitation}
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
            completion={{ kind: 'content-spec', oncomplete: handleComplete }}
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
