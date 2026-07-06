<!-- @component Revisitable editing panel for a markdown field's pending inline
  cites: one row per [[cite:slug]] marker inserted this session, with the
  locator and quote editable until save (nothing mints until then). A row
  appears when the picker inserts its marker and disappears when the marker is
  deleted from the text; already-saved cites are immutable and never show.
  Fields use the same FieldGroup label + persistent hint pattern as the
  picker's locator stage — never placeholder text as the only guidance. -->
<script lang="ts">
  import { tick } from 'svelte';
  import { pendingCitationsInText, type PendingInlineCitation } from '$lib/pending-citations';
  import { citationTypeMeta } from '$lib/citation-types';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';

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

  // The locator is unprompted but reachable (same rule as EditCitationField):
  // most cites — a web page pinned by its URL — never need one, so a row shows
  // only "Add a locator" until the cite carries a locator (entered at the
  // picker's locator stage) or the contributor opens it here. Once opened it
  // stays visible for the session, so a cleared value doesn't yank the field
  // out from under the contributor.
  let locatorAdded = $state(new Set<string>());
  let locatorInputs: Record<string, HTMLInputElement | undefined> = $state({});

  function locatorVisible(citation: PendingInlineCitation): boolean {
    return !!citation.locator || locatorAdded.has(citation.slug);
  }

  async function addLocator(slug: string) {
    locatorAdded = new Set([...locatorAdded, slug]);
    await tick();
    locatorInputs[slug]?.focus();
  }
</script>

{#if visible.length > 0}
  <div class="inline-citations">
    <span class="panel-label">Inline citations</span>
    {#each visible as citation (citation.slug)}
      {@const meta = citationTypeMeta(citation.sourceType)}
      <div class="citation-row" role="group" aria-label={citation.sourceName}>
        <div class="citation-summary">{citation.sourceName}</div>
        {#if locatorVisible(citation)}
          <FieldGroup label={meta.locatorLabel} hint={meta.locatorHelp} optional>
            {#snippet children(inputId, describedBy)}
              <input
                bind:this={locatorInputs[citation.slug]}
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
        {#if !locatorVisible(citation)}
          <div>
            <button
              type="button"
              class="add-locator-button"
              onclick={() => addLocator(citation.slug)}
            >
              Add a locator
            </button>
          </div>
        {/if}
      </div>
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

  .citation-row {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
    padding: var(--size-2) var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
  }

  .citation-summary {
    color: var(--color-text);
    font-size: var(--font-size-1);
  }

  .add-locator-button {
    padding: var(--size-1) var(--size-3);
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
    background: var(--color-input-bg);
    color: var(--color-text-muted);
    font: inherit;
    cursor: pointer;
  }
</style>
