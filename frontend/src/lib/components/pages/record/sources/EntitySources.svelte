<!-- @component The per-entity Sources page: every claim field in one list, each
showing the distinct values asserted for it, who backs each value and the
citations behind it, with the losing values de-emphasized beneath the winner. -->
<script lang="ts">
  import type { ClaimSchema } from '$lib/api/schema';
  import ClaimAuthor from '$lib/components/provenance/ClaimAuthor.svelte';
  import ClaimValue from '$lib/components/provenance/ClaimValue.svelte';
  import FocusContentShell from '$lib/components/layout/page/FocusContentShell.svelte';
  import CitationBody from '$lib/components/citation/CitationBody.svelte';
  import { getEntityContext } from '$lib/entity-context';
  import { buildSourcesView, type ValueSupport } from './entity-sources';

  let { sources }: { sources: ClaimSchema[] } = $props();

  let view = $derived(buildSourcesView(sources));
  const entity = getEntityContext();
</script>

{#snippet valueRow(entry: ValueSupport)}
  <div class="value-row" class:displaced={!entry.isWinner}>
    <span class="value">
      <ClaimValue value={entry.value} /><!--
     --><sup class="refs"
        >{#each entry.citationNumbers as number (number)}<a
            href="#citation-{number}"
            title="Jump to citation {number}">[{number}]</a
          >{/each}</sup
      >
    </span>
    <span class="support">
      {#each entry.supporters as attribution, i (i)}
        <ClaimAuthor {attribution} />
      {/each}
    </span>
  </div>
{/snippet}

<FocusContentShell
  backHref={entity.detailHref}
  recordName={entity.name}
  recordHref={entity.detailHref}
  maxWidth="64rem"
>
  {#snippet heading()}
    <h1 class="page-label">Sources</h1>
  {/snippet}

  {#if sources.length > 0}
    <p class="summary">
      Contributors to this record:
      <!-- The separator is an expression, not markup: Svelte trims the
      whitespace off a literal ", " and the line copies as "moses,OPDB". -->
      {#each view.contributors as attribution, i (i)}<ClaimAuthor {attribution} />{i <
        view.contributors.length - 1
          ? ', '
          : '.'}{/each}
    </p>

    <dl class="fields">
      {#each view.fields as field (field.field)}
        <div class="field">
          <dt>{field.field}</dt>
          <dd>
            {#each field.slots as slot (slot.claimKey)}
              <div class="slot">
                {@render valueRow(slot.winner)}
                {#if slot.others.length > 0}
                  <p class="others-label">Other values claimed:</p>
                  {#each slot.others as entry (entry.key)}
                    {@render valueRow(entry)}
                  {/each}
                {/if}
              </div>
            {/each}
          </dd>
        </div>
      {/each}
    </dl>

    {#if view.references.length > 0}
      <section class="references">
        <h2>Citations</h2>
        <ol>
          {#each view.references as citation, i (i)}
            <li id="citation-{i + 1}">
              <CitationBody {citation} layout="inline" />
            </li>
          {/each}
        </ol>
      </section>
    {/if}
  {:else}
    <p class="no-sources">No source data recorded yet.</p>
  {/if}
</FocusContentShell>

<style>
  .page-label {
    margin: 0;
    font-size: inherit;
    font-weight: inherit;
    color: inherit;
  }

  /* Inline flow, not flex: a comma is a text node, and flex would make it its
     own item with gap on both sides ("IPDB , OPDB"). Inline also gives the
     paragraph real text content — under flex the gaps are layout only, so the
     line copied and read aloud as "moses" run into "OPDB". The pills flow here
     unchanged, being inline-block already; line-height does the work row-gap
     used to. */
  .summary {
    font-size: var(--font-size-0);
    line-height: 1.9;
    color: var(--color-text-muted);
    margin-bottom: var(--size-4);
  }

  .fields {
    margin: 0;
  }

  .field {
    display: grid;
    grid-template-columns: minmax(8rem, 12rem) minmax(0, 1fr);
    gap: var(--size-3);
    padding: var(--size-3) 0;
    border-bottom: 1px solid var(--color-border-soft);
  }

  .field dt {
    font-weight: 500;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    overflow-wrap: anywhere;
  }

  /* A slot's displaced values sit at the same rhythm as a multi-valued
     field's sibling slots — the "Other values claimed" lead-in is what marks
     them as losing, so neither the winner nor the field needs a badge. */
  .field dd,
  .slot {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .field dd {
    margin: 0;
    min-width: 0;
  }

  .others-label {
    margin: 0;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    /* Full strength: the label has to stay legible over the values it
       introduces, which carry the de-emphasis. */
  }

  .value-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 15rem);
    gap: var(--size-1) var(--size-3);
    align-items: baseline;
    font-size: var(--font-size-0);
    color: var(--color-text);
  }

  .value-row.displaced {
    opacity: 0.5;
  }

  .value {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .support {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  /* Bracketed superscript, the encyclopedia convention: a bare number riding a
     numeric value ("4 3" for player_count) reads as part of the value. */
  .refs {
    font-size: 0.85em;
  }

  .refs a {
    margin-left: 2px;
    color: var(--color-link);
    text-decoration: none;
    font-variant-numeric: tabular-nums;
  }

  .refs a:hover {
    text-decoration: underline;
  }

  .references {
    margin-top: var(--size-6);
  }

  .references h2 {
    font-size: var(--font-size-2);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  .references ol {
    margin: 0;
    padding-left: var(--size-5);
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
    font-size: var(--font-size-0);
  }

  .references li {
    /* Anchor targets: keep the number in view when jumped to from a ref. */
    scroll-margin-top: var(--size-5);
  }

  .no-sources {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }

  @media (--breakpoint-narrow) {
    .field {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--size-1);
    }

    .value-row {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
