<script lang="ts">
  import AccordionSection from '$lib/components/ui/AccordionSection.svelte';
  import ModelHierarchy from '$lib/components/pages/record/detail/ModelHierarchy.svelte';
  import ModelSpecsSidebar from '$lib/components/pages/record/detail/ModelSpecsSidebar.svelte';
  import CreditsList from '$lib/components/pages/record/detail/CreditsList.svelte';
  import MediaGrid from '$lib/components/media/MediaGrid.svelte';
  import { ENTITY_META } from '$lib/entities/entity-meta';
  import RichTextOverviewAccordion from '$lib/components/markdown/RichTextOverviewAccordion.svelte';
  import RichTextReferencesAccordion from '$lib/components/markdown/RichTextReferencesAccordion.svelte';
  import { createRichTextAccordionState } from '$lib/components/markdown/rich-text-accordion-state.svelte';
  import ModelRelationshipsList from './_components/ModelRelationshipsList.svelte';
  import { modelEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import { externalLinks } from '$lib/entities/external-links';
  import { model as modelInfo } from '$lib/entities/model';

  let { data } = $props();
  let model = $derived(data.profile);

  // On desktop, editAction opens the modal editor; on mobile, it navigates to the edit route.
  const editAction = modelEditActionContext.get();
  const richTextState = createRichTextAccordionState();

  let hasRelationships = $derived(
    model.title ||
      model.variants.length > 0 ||
      model.variant_of ||
      (model.variant_siblings && model.variant_siblings.length > 0) ||
      model.converted_from ||
      (model.conversions && model.conversions.length > 0) ||
      model.remake_of ||
      (model.remakes && model.remakes.length > 0) ||
      model.title_models.length > 1,
  );
  let hasTechnology = $derived(
    !!model.technology_generation ||
      !!model.technology_subgeneration ||
      !!model.display_type ||
      !!model.display_subtype ||
      !!model.system,
  );
  let hasFeatures = $derived(
    !!model.game_format ||
      !!model.cabinet ||
      (model.reward_types?.length ?? 0) > 0 ||
      model.themes.length > 0 ||
      !!model.production_quantity ||
      !!model.player_count ||
      !!model.flipper_count ||
      model.gameplay_features.length > 0 ||
      !!model.franchise ||
      !!model.series ||
      model.variant_features.length > 0,
  );
  let peopleHeading = $derived(`People (${model.credits.length})`);
  let mediaHeading = $derived(`Media (${model.uploaded_media.length})`);
  let externalSiteLinks = $derived(externalLinks(model, modelInfo));
</script>

{#if model.description?.html}
  <RichTextOverviewAccordion
    richText={model.description}
    state={richTextState}
    onEdit={editAction('overview')}
  />
{/if}

<!-- Technology — mobile only -->
{#if hasTechnology}
  <div class="mobile-only">
    <AccordionSection heading="Technology" onEdit={editAction('technology')}>
      <ModelSpecsSidebar {model} section="technology" />
    </AccordionSection>
  </div>
{/if}

<!-- Features — mobile only -->
{#if hasFeatures}
  <div class="mobile-only">
    <AccordionSection heading="Features" onEdit={editAction('features')}>
      <ModelSpecsSidebar {model} section="features" />
    </AccordionSection>
  </div>
{/if}

<!-- People -->
{#if model.credits.length > 0}
  <AccordionSection heading={peopleHeading} onEdit={editAction('people')}>
    <CreditsList credits={model.credits} showHeading={false} />
  </AccordionSection>
{/if}

<!-- Related Models — mobile only -->
{#if hasRelationships}
  <div class="mobile-only">
    <AccordionSection heading="Related Models" onEdit={editAction('related-models')}>
      <ModelRelationshipsList {model} />
      <ModelHierarchy
        models={model.title_models}
        heading="Other Models In Title"
        excludeSlug={model.variant_of?.public_id ?? model.slug}
        inline
      />
    </AccordionSection>
  </div>
{/if}

<!-- Media -->
{#if model.uploaded_media.length > 0}
  <AccordionSection heading={mediaHeading} onEdit={editAction('media')}>
    <MediaGrid
      media={model.uploaded_media}
      categories={[...ENTITY_META.model.media_categories]}
      canEdit={false}
    />
  </AccordionSection>
{/if}

<!-- External Links — mobile only -->
{#if externalSiteLinks.length}
  <div class="mobile-only">
    <AccordionSection heading="External Links" onEdit={editAction('external-data')}>
      <p class="external-note">See this model on other sites:</p>
      <div class="external-ids">
        {#each externalSiteLinks as link (link.href)}
          <a href={link.href}>{link.label}</a>
        {/each}
      </div>
    </AccordionSection>
  </div>
{/if}

<RichTextReferencesAccordion richText={model.description} state={richTextState} />

<style>
  /* Mobile-only: hidden once the sidebar appears at the wide breakpoint. */
  .mobile-only {
    display: block;
  }

  @media (--breakpoint-wide) {
    .mobile-only {
      display: none;
    }
  }

  .external-note {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-2);
  }

  .external-ids {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-3);
    font-size: var(--font-size-0);
  }
</style>
