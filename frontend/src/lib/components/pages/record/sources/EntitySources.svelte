<!-- @component The per-entity Sources page: every claim field in one list, each
showing the distinct values asserted for it, who backs each value and the
citations behind it, with the losing values de-emphasized beneath the winner. -->
<script lang="ts">
  import { tick } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import type { ClaimSchema } from '$lib/api/schema';
  import ChangeValue from '$lib/components/provenance/ChangeValue.svelte';
  import ClaimAuthor from '$lib/components/provenance/ClaimAuthor.svelte';
  import FocusContentShell from '$lib/components/layout/page/FocusContentShell.svelte';
  import CitationReference from '$lib/components/markdown/CitationReference.svelte';
  import CitationTooltip from '$lib/components/markdown/CitationTooltip.svelte';
  import CollapsibleBlock from '$lib/components/ui/CollapsibleBlock.svelte';
  import { findFirstInlineMarker, findRefEntry } from '$lib/components/markdown/citation-refs';
  import { getEntityContext } from '$lib/entity-context';
  import { buildSourcesView, type ValueSupport } from './entity-sources';

  let { sources }: { sources: ClaimSchema[] } = $props();

  let view = $derived(buildSourcesView(sources));
  const entity = getEntityContext();

  /** Wraps every marker on the page, so one tooltip serves them all. */
  let fieldsEl: HTMLDivElement | undefined = $state();
  let refsEl: HTMLElement | undefined = $state();
  let highlightedRef: number | null = $state(null);
  let flashedMarker: number | null = $state(null);
  /** Prose values the reader has opened, by `ValueSupport.uid`. */
  const expandedValues = new SvelteSet<string>();

  /** Re-runs the tooltip's listener scan whenever the markers change. Keyed on
   *  the reference identities, which is what the markers are drawn from. */
  let markerSignal = $derived(view.references.map((c) => c.id).join(','));

  /** Fragment target of a reference number. The tooltip intercepts the click
   *  to scroll and flash; the href is what makes the jump work regardless. */
  const citationHref = (index: number) => `#citation-${index}`;

  /** A marker was activated: jump to its entry in the citation list. */
  async function scrollToRef(index: number) {
    // Clear first so a repeat jump to the same entry replays the flash.
    highlightedRef = null;
    await tick();
    highlightedRef = index;
    await tick();
    if (refsEl)
      findRefEntry(refsEl, index)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  /** Every value that renders a marker for *index*. */
  function valuesCiting(index: number): ValueSupport[] {
    return view.fields
      .flatMap((field) => field.slots)
      .flatMap((slot) => [slot.winner, ...slot.others])
      .filter((entry) => entry.citeIds.get(index) !== undefined);
  }

  /** A citation's back-link was activated: scroll to its first marker. Every
   *  marker carrying that number flashes, since the reader may want the rest. */
  async function scrollToMarker(index: number) {
    // A collapsed value clips its own markers, so open the ones that carry
    // this number before looking for it — otherwise the jump lands on
    // something the reader cannot see.
    for (const entry of valuesCiting(index)) expandedValues.add(entry.uid);
    flashedMarker = null;
    await tick();
    flashedMarker = index;
    await tick();
    if (fieldsEl) {
      findFirstInlineMarker(fieldsEl, index)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }

  function setExpanded(uid: string, expanded: boolean): void {
    if (expanded) expandedValues.add(uid);
    else expandedValues.delete(uid);
  }
</script>

{#snippet valueText(entry: ValueSupport)}
  <ChangeValue
    value={entry.value}
    citeIndexes={entry.citeIndexes}
    interactions={{ ids: entry.citeIds, hrefFor: citationHref, flashIndex: flashedMarker }}
  /><!--
 -->{#each entry.footnotes as footnote (footnote.index)}<sup class="cite-marker"
      ><a
        href={citationHref(footnote.index)}
        class:flash={footnote.index === flashedMarker}
        data-cite-id={footnote.id}
        data-cite-index={footnote.index}
        aria-label="Citation {footnote.index}">[{footnote.index}]</a
      ></sup
    >{/each}
{/snippet}

{#snippet valueRow(entry: ValueSupport)}
  <div class="value-row" class:displaced={!entry.isWinner}>
    <div class="value">
      {#if entry.isProse}
        <!-- Two lines until asked: a description runs to paragraphs, and a
             contested one is rendered once per editor who has touched it. The
             second line is what the fade acts on — cut to one, there is nothing
             trailing off and "Show more" reads as unattached to anything. -->
        <CollapsibleBlock
          collapsedHeight="2lh"
          expanded={expandedValues.has(entry.uid)}
          onExpandedChange={(next) => setExpanded(entry.uid, next)}
          signal={entry.uid}
        >
          {@render valueText(entry)}
        </CollapsibleBlock>
      {:else}
        {@render valueText(entry)}
      {/if}
    </div>
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

    <div bind:this={fieldsEl}>
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
    </div>
    <CitationTooltip
      container={fieldsEl}
      contentSignal={markerSignal}
      citations={view.references}
      onNavigate={scrollToRef}
    />

    {#if view.references.length > 0}
      <section class="references" bind:this={refsEl}>
        <h2>Citations</h2>
        <ol>
          {#each view.references as citation (citation.index)}
            <CitationReference
              index={citation.index}
              {citation}
              anchorId="citation-{citation.index}"
              onBackLink={scrollToMarker}
              highlighted={citation.index === highlightedRef}
              onFlashEnd={() => (highlightedRef = null)}
            />
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
    font-size: var(--font-size-1);
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

  /* Colour rather than opacity, and on the value alone: opacity on the row
     would fade the citation markers and supporter chips too, pushing text
     that is already muted under the contrast floor. */
  .value-row.displaced .value {
    color: var(--color-text-muted);
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
     numeric value ("4 3" for player_count) reads as part of the value. Sized to
     match the inline markers these sit alongside. */
  .cite-marker {
    margin-left: 2px;
    font-size: var(--font-size-00, 0.75rem);
    line-height: 0;
    color: var(--color-link);
    font-variant-numeric: tabular-nums;
  }

  .cite-marker a {
    color: inherit;
    text-decoration: none;
  }

  .cite-marker a:hover,
  .cite-marker a:focus-visible {
    text-decoration: underline;
  }

  .cite-marker a.flash {
    animation: cite-flash 1.5s ease-out;
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

  /* The entries bring their own spacing and flash, so only the list box is
     styled here. */
  .references ol {
    margin: 0;
    padding-left: var(--size-5);
    font-size: var(--font-size-0);
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

  /* Scoped per component: `no-unknown-animations` resolves keyframes within a
     stylesheet, so a shared global one would not satisfy it — and Svelte hashes
     a local @keyframes together with the rule referencing it. */
  @keyframes cite-flash {
    from {
      background-color: var(--color-highlight-bg);
    }

    to {
      background-color: transparent;
    }
  }
</style>
