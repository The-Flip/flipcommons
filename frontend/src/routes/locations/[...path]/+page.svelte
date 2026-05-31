<script lang="ts">
  import AccordionSection from '$lib/components/AccordionSection.svelte';
  import ManufacturerCardGrid from './_components/ManufacturerCardGrid.svelte';
  import RichTextOverviewAccordion from '$lib/components/markdown/RichTextOverviewAccordion.svelte';
  import RichTextReferencesAccordion from '$lib/components/markdown/RichTextReferencesAccordion.svelte';
  import { createRichTextAccordionState } from '$lib/components/markdown/rich-text-accordion-state.svelte';
  import { locationEditActionContext } from '$lib/components/editors/edit-action-context';
  import JsonLd from '$lib/components/JsonLd.svelte';
  import type { LocationDetailSchema } from '$lib/api/schema';

  type LocationDetail = LocationDetailSchema;

  let { data } = $props();
  let profile = $derived<LocationDetail>(data.profile);
  let editAction = locationEditActionContext.get();
  const richTextState = createRichTextAccordionState();
  let manufacturersHeading = $derived(`Manufacturers (${profile.manufacturer_count})`);
</script>

<!-- Rendered here (the detail leaf), not the layout: the `[...path]` rest
     param defeats the shared subroute matcher, and this leaf only renders on
     the exact detail route. `data.jsonLd` is undefined for the global root. -->
{#if data.jsonLd}
  <JsonLd data={data.jsonLd} />
{/if}

{#if profile.description?.html}
  <RichTextOverviewAccordion
    richText={profile.description}
    state={richTextState}
    onEdit={editAction('description')}
  />
{/if}

<AccordionSection heading={manufacturersHeading} open={true}>
  <ManufacturerCardGrid manufacturers={profile.manufacturers} showCount={false} />
</AccordionSection>

<RichTextReferencesAccordion richText={profile.description} state={richTextState} />
