<!-- @component Revisitable editing panel for a markdown field's pending inline
  cites: one row per [[cite:slug]] marker inserted this session, with the
  locator and quote editable until save (nothing mints until then). A row
  appears when the picker inserts its marker and disappears when the marker is
  deleted from the text; already-saved cites are immutable and never show.
  Rows are the shared CitationInstanceFields body (FieldGroup label + hint
  fields, add-locator reveal); a row carries no buttons of its own — deleting
  the marker is how a pending inline cite is removed. -->
<script lang="ts">
  import { pendingCitationsInText, type PendingInlineCitation } from '$lib/pending-citations';
  import CitationInstanceFields from './CitationInstanceFields.svelte';

  let {
    pending,
    text,
  }: {
    /** All pending cites the host holds. Rows edit these entries in place. */
    pending: PendingInlineCitation[];
    /** The markdown value; only cites whose marker survives in it show. */
    text: string;
  } = $props();

  let visible = $derived(pendingCitationsInText(pending, text));
</script>

{#if visible.length > 0}
  <div class="inline-citations">
    <span class="panel-label">Inline citations</span>
    {#each visible as citation (citation.slug)}
      <CitationInstanceFields {citation} />
    {/each}
  </div>
{/if}

<style>
  .inline-citations {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .panel-label {
    font-size: var(--font-size-0);
    font-weight: var(--font-weight-6);
    color: var(--color-text-muted);
  }
</style>
