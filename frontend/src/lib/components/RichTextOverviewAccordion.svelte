<script lang="ts">
  import AccordionSection from './AccordionSection.svelte';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from './Markdown.svelte';
  import type { InlineCitation } from './citation-tooltip';
  import type { RichTextAccordionState } from './rich-text-accordion-state.svelte';

  type RichTextValue = {
    text?: string;
    html?: string;
    citations?: InlineCitation[];
    attribution?: object | null;
  } | null;

  let {
    richText = null,
    state,
    heading = 'Overview',
    open = true,
    onEdit = undefined,
  }: {
    richText?: RichTextValue;
    state: RichTextAccordionState;
    heading?: string;
    open?: boolean;
    onEdit?: (() => void) | undefined;
  } = $props();
</script>

{#if richText?.html}
  <AccordionSection {heading} {open} {onEdit}>
    <div bind:this={state.descriptionContentEl}>
      <Markdown
        html={richText.html}
        citations={richText.citations ?? []}
        showReferences={false}
        onNavigateToRef={state.scrollToRefEntry}
      />
      <AttributionLine attribution={richText.attribution} />
    </div>
  </AccordionSection>
{/if}
