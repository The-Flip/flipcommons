<!-- @component Shared row body for one citation being refined until save: the
  source-name summary plus FieldGroup-labeled locator and quote fields — the
  label + persistent-hint pattern, never placeholder text as the only guidance
  — and the "Add a locator" reveal. Consumed by the edit form's citation list
  (EditCitationField) and the inline-citations panel; consumers pass their own
  row actions (`onremove` renders a header Remove button, the `actions` snippet
  lands in the bottom action row). -->
<script lang="ts">
  import { tick } from 'svelte';
  import type { Snippet } from 'svelte';
  import { citationTypeMeta } from '$lib/citation-types';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';

  /** The slice of a pending citation this row edits in place. Structural, so
   *  both hosts' richer shapes (EditCitationSelection, PendingInlineCitation)
   *  satisfy it without conversion. */
  interface CitationFieldsValue {
    sourceName: string;
    sourceType: string;
    locator: string;
    quote: string;
  }

  let {
    citation = $bindable(),
    onremove,
    actions,
  }: {
    citation: CitationFieldsValue;
    /** Renders a "Remove" button beside the source name when provided. */
    onremove?: () => void;
    /** Extra consumer-specific buttons for the bottom action row. */
    actions?: Snippet;
  } = $props();

  // The source's citation type drives the locator prompt (a video asks for a
  // start time; books and pages stay freeform).
  let meta = $derived(citationTypeMeta(citation.sourceType));

  // The locator is unprompted but reachable: most cites never need one, so the
  // field shows only after "Add a locator" — and stays visible once it has
  // ever held text this session, so a cleared value doesn't yank the field out
  // from under the contributor.
  let locatorAdded = $state(false);
  let locatorInput: HTMLInputElement | undefined = $state();
  let locatorVisible = $derived(!!citation.locator || locatorAdded);

  async function addLocator() {
    locatorAdded = true;
    await tick();
    locatorInput?.focus();
  }
</script>

<div class="citation-row" role="group" aria-label={citation.sourceName}>
  <div class="citation-header">
    <div class="citation-summary">{citation.sourceName}</div>
    {#if onremove}
      <button type="button" class="row-button" onclick={onremove}>Remove</button>
    {/if}
  </div>
  {#if locatorVisible}
    <FieldGroup label={meta.locatorLabel} hint={meta.locatorHelp} optional>
      {#snippet children(inputId, describedBy)}
        <input
          bind:this={locatorInput}
          id={inputId}
          type="text"
          aria-describedby={describedBy}
          maxlength="200"
          bind:value={citation.locator}
        />
      {/snippet}
    </FieldGroup>
  {/if}
  <FieldGroup label="Quote" hint="Exact text quoted from the source" optional>
    {#snippet children(inputId, describedBy)}
      <textarea
        id={inputId}
        aria-describedby={describedBy}
        rows="3"
        maxlength="2000"
        bind:value={citation.quote}></textarea>
    {/snippet}
  </FieldGroup>
  {#if !locatorVisible || actions}
    <div class="citation-actions">
      {#if !locatorVisible}
        <button type="button" class="row-button" onclick={addLocator}>Add a locator</button>
      {/if}
      {#if actions}{@render actions()}{/if}
    </div>
  {/if}
</div>

<style>
  .citation-row {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
    padding: var(--size-2) var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
  }

  .citation-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--size-2);
  }

  .citation-summary {
    color: var(--color-text);
    font-size: var(--font-size-1);
  }

  .citation-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-2);
  }

  .row-button {
    padding: var(--size-1) var(--size-3);
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
    background: var(--color-input-bg);
    color: var(--color-text-muted);
    font: inherit;
    cursor: pointer;
  }
</style>
