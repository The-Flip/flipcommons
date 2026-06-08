<script lang="ts">
  import { resolve } from '$app/paths';
  import AccordionSection from '$lib/components/ui/AccordionSection.svelte';
  import CardGrid from '$lib/components/collections/grid/CardGrid.svelte';
  import CreditsList from '$lib/components/pages/record/detail/CreditsList.svelte';
  import MachineCard from '$lib/components/collections/cards/MachineCard.svelte';
  import MediaGrid from '$lib/components/media/MediaGrid.svelte';
  import ModelSpecsSidebar from '$lib/components/pages/record/detail/ModelSpecsSidebar.svelte';
  import RichTextOverviewAccordion from '$lib/components/markdown/RichTextOverviewAccordion.svelte';
  import RichTextReferencesAccordion from '$lib/components/markdown/RichTextReferencesAccordion.svelte';
  import { createRichTextAccordionState } from '$lib/components/markdown/rich-text-accordion-state.svelte';
  import RelatedTitlesSection from './_components/RelatedTitlesSection.svelte';
  import CreateFirstModelPrompt from './_components/CreateFirstModelPrompt.svelte';
  import { titleAreaEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import { externalLinks } from '$lib/entities/external-links';
  import { model as modelInfo } from '$lib/entities/model';
  import { title as titleInfo } from '$lib/entities/title';

  let { data } = $props();
  let title = $derived(data.profile);
  let md = $derived(title.model_detail);
  let specs = $derived(title.agreed_specs);
  let overviewRichText = $derived(md ? md.description : title.description);
  let hasOverview = $derived(!!overviewRichText?.html);

  // Desktop: opens the layout's SectionEditorHost modal. Mobile: navigates to
  // the appropriate edit route. Returns undefined when unauthenticated.
  const editAction = titleAreaEditActionContext.get();
  const richTextState = createRichTextAccordionState();

  // Flatten parents and variants into a single grid — no hierarchy.
  let flatModels = $derived.by(() => {
    const out: Array<{
      slug: string;
      name: string;
      year: number | null | undefined;
      thumbnailUrl: string | null | undefined;
      manufacturerName: string | null;
    }> = [];
    for (const m of title.machines) {
      out.push({
        slug: m.public_id,
        name: m.name,
        year: m.year,
        thumbnailUrl: m.thumbnail_url,
        manufacturerName: m.manufacturer?.name ?? null,
      });
      for (const v of m.variants ?? []) {
        out.push({
          slug: v.public_id,
          name: v.name,
          year: v.year,
          thumbnailUrl: v.thumbnail_url,
          manufacturerName: m.manufacturer?.name ?? null,
        });
      }
    }
    return out;
  });

  let hasTechnology = $derived(
    !!(
      specs.technology_generation ||
      specs.technology_subgeneration ||
      specs.display_type ||
      specs.display_subtype ||
      specs.system
    ),
  );

  let hasFeatures = $derived(
    !!(
      specs.production_status ||
      specs.game_format ||
      specs.cabinet ||
      specs.player_count ||
      specs.flipper_count ||
      specs.production_quantity ||
      (specs.themes && specs.themes.length > 0) ||
      (specs.gameplay_features && specs.gameplay_features.length > 0) ||
      (specs.reward_types && specs.reward_types.length > 0) ||
      (specs.tags && specs.tags.length > 0) ||
      title.franchise ||
      title.series
    ),
  );

  // External-DB links, one source of truth shared with the sidebar and JSON-LD.
  // The single-model view shows the Model's (IPDB/Pinside) + the Title's
  // (Fandom); the multi-model view shows only the Title's.
  let titleLinks = $derived(externalLinks(title, titleInfo));
  let modelLinks = $derived(md ? externalLinks(md, modelInfo) : []);
  let combinedLinks = $derived([...modelLinks, ...titleLinks]);
</script>

{#if md}
  <!-- Single-model title: sections sourced from the one model's detail. -->
  {#if hasOverview}
    <RichTextOverviewAccordion
      richText={overviewRichText}
      state={richTextState}
      onEdit={editAction('model:overview')}
    />
  {/if}

  {#if md.technology_generation || md.technology_subgeneration || md.display_type || md.display_subtype || md.system}
    <AccordionSection heading="Technology" onEdit={editAction('model:technology')}>
      <ModelSpecsSidebar model={md} section="technology" />
    </AccordionSection>
  {/if}

  <AccordionSection heading="Features" onEdit={editAction('model:features')}>
    <ModelSpecsSidebar model={md} section="features" />
  </AccordionSection>

  {#if title.related_titles && title.related_titles.length > 0}
    <AccordionSection heading="Related Titles">
      <RelatedTitlesSection relatedTitles={title.related_titles} />
    </AccordionSection>
  {/if}

  {#if md.credits.length > 0}
    <AccordionSection heading="People ({md.credits.length})" onEdit={editAction('model:people')}>
      <CreditsList credits={md.credits} showHeading={false} />
    </AccordionSection>
  {/if}

  {#if md.uploaded_media.length > 0}
    <AccordionSection
      heading="Media ({md.uploaded_media.length})"
      onEdit={editAction('model:media')}
    >
      <MediaGrid media={md.uploaded_media} canEdit={false} />
    </AccordionSection>
  {/if}

  {#if combinedLinks.length}
    <AccordionSection heading="External Links" onEdit={editAction('model:external-data')}>
      <div class="external-ids">
        {#each combinedLinks as link (link.href)}
          <a href={link.href}>{link.label}</a>
        {/each}
      </div>
    </AccordionSection>
  {/if}

  <RichTextReferencesAccordion richText={overviewRichText} state={richTextState} />
{:else}
  <!-- "Create first model" CTA when the title has no models. Shown to all
	     viewers (spec: "shown to any user viewing that page until the first
	     model is created") — anonymous users clicking through get bounced
	     to login by the create page's load guard. -->
  {#if flatModels.length === 0}
    <CreateFirstModelPrompt titleSlug={title.slug} titleName={title.name} />
  {/if}

  <!-- Overview -->
  {#if hasOverview}
    <RichTextOverviewAccordion
      richText={overviewRichText}
      state={richTextState}
      onEdit={editAction('title:overview')}
    />
  {/if}

  <!-- Models — flat grid including variants -->
  {#if flatModels.length > 0}
    <AccordionSection heading="Models ({flatModels.length})">
      <CardGrid>
        {#each flatModels as m (m.slug)}
          <MachineCard
            slug={m.slug}
            name={m.name}
            thumbnailUrl={m.thumbnailUrl}
            manufacturerName={m.manufacturerName}
            year={m.year}
          />
        {/each}
      </CardGrid>
    </AccordionSection>
  {/if}

  <!-- Technology — intersection of models' technology fields -->
  {#if hasTechnology}
    <AccordionSection heading="Technology">
      <dl>
        {#if specs.technology_generation}
          <dt>Generation</dt>
          <dd>
            <a href={resolve(`/technology-generations/${specs.technology_generation.public_id}`)}
              >{specs.technology_generation.name}</a
            >
          </dd>
        {/if}
        {#if specs.technology_subgeneration}
          <dt>Subgeneration</dt>
          <dd>
            <a
              href={resolve(
                `/technology-subgenerations/${specs.technology_subgeneration.public_id}`,
              )}>{specs.technology_subgeneration.name}</a
            >
          </dd>
        {/if}
        {#if specs.display_type}
          <dt>Display Type</dt>
          <dd>
            <a href={resolve(`/display-types/${specs.display_type.public_id}`)}
              >{specs.display_type.name}</a
            >
          </dd>
        {/if}
        {#if specs.display_subtype}
          <dt>Display Subtype</dt>
          <dd>
            <a href={resolve(`/display-subtypes/${specs.display_subtype.public_id}`)}
              >{specs.display_subtype.name}</a
            >
          </dd>
        {/if}
        {#if specs.system}
          <dt>System</dt>
          <dd>
            <a href={resolve(`/systems/${specs.system.public_id}`)}>{specs.system.name}</a>
          </dd>
        {/if}
      </dl>
    </AccordionSection>
  {/if}

  <!-- Features — intersection of models' features + franchise / series at title tier -->
  {#if hasFeatures}
    <AccordionSection heading="Features">
      <dl>
        {#if title.franchise}
          <dt>Franchise</dt>
          <dd>
            <a href={resolve(`/franchises/${title.franchise.public_id}`)}>{title.franchise.name}</a>
          </dd>
        {/if}
        {#if title.series}
          <dt>Series</dt>
          <dd>
            <a href={resolve(`/series/${title.series.public_id}`)}>{title.series.name}</a>
          </dd>
        {/if}
        {#if specs.game_format}
          <dt>Format</dt>
          <dd>
            <a href={resolve(`/game-formats/${specs.game_format.public_id}`)}
              >{specs.game_format.name}</a
            >
          </dd>
        {/if}
        {#if specs.cabinet}
          <dt>Cabinet</dt>
          <dd>
            <a href={resolve(`/cabinets/${specs.cabinet.public_id}`)}>{specs.cabinet.name}</a>
          </dd>
        {/if}
        {#if specs.production_status}
          <dt>Production status</dt>
          <dd>
            <a href={resolve(`/production-statuses/${specs.production_status.public_id}`)}
              >{specs.production_status.name}</a
            >
          </dd>
        {/if}
        {#if specs.player_count}
          <dt>Players</dt>
          <dd>{specs.player_count}</dd>
        {/if}
        {#if specs.flipper_count}
          <dt>Flippers</dt>
          <dd>{specs.flipper_count}</dd>
        {/if}
        {#if specs.production_quantity}
          <dt>Units Made</dt>
          <dd>{specs.production_quantity}</dd>
        {/if}
        {#if specs.themes && specs.themes.length > 0}
          <dt>Themes</dt>
          <dd>
            {#each specs.themes as theme, i (theme.public_id)}
              {#if i > 0},
              {/if}
              <a href={resolve(`/themes/${theme.public_id}`)}>{theme.name}</a>
            {/each}
          </dd>
        {/if}
        {#if specs.gameplay_features && specs.gameplay_features.length > 0}
          <dt>Gameplay</dt>
          <dd>
            {#each specs.gameplay_features as gf, i (gf.public_id)}
              {#if i > 0},
              {/if}
              <a href={resolve(`/gameplay-features/${gf.public_id}`)}>{gf.name}</a
              >{#if gf.count}&nbsp;({gf.count}){/if}
            {/each}
          </dd>
        {/if}
        {#if specs.reward_types && specs.reward_types.length > 0}
          <dt>Reward Types</dt>
          <dd>
            {#each specs.reward_types as rt, i (rt.public_id)}
              {#if i > 0},
              {/if}
              <a href={resolve(`/reward-types/${rt.public_id}`)}>{rt.name}</a>
            {/each}
          </dd>
        {/if}
        {#if specs.tags && specs.tags.length > 0}
          <dt>Tags</dt>
          <dd>
            {#each specs.tags as tag, i (tag.public_id)}
              {#if i > 0},
              {/if}
              <a href={resolve(`/tags/${tag.public_id}`)}>{tag.name}</a>
            {/each}
          </dd>
        {/if}
      </dl>
    </AccordionSection>
  {/if}

  <!-- Related Titles — union of cross-title conversion/remake links -->
  {#if title.related_titles && title.related_titles.length > 0}
    <AccordionSection heading="Related Titles">
      <RelatedTitlesSection relatedTitles={title.related_titles} />
    </AccordionSection>
  {/if}

  <!-- People — intersection of credits across models -->
  {#if title.credits.length > 0}
    <AccordionSection heading="People ({title.credits.length})">
      <CreditsList credits={title.credits} showHeading={false} />
    </AccordionSection>
  {/if}

  <!-- Media — union across models -->
  {#if title.media.length > 0}
    <AccordionSection heading="Media ({title.media.length})">
      <MediaGrid media={title.media} canEdit={false} />
    </AccordionSection>
  {/if}

  <!-- External Links -->
  {#if titleLinks.length}
    <AccordionSection heading="External Links" onEdit={editAction('title:external-data')}>
      <div class="external-ids">
        {#each titleLinks as link (link.href)}
          <a href={link.href}>{link.label}</a>
        {/each}
      </div>
    </AccordionSection>
  {/if}

  <RichTextReferencesAccordion richText={overviewRichText} state={richTextState} />
{/if}

<style>
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--size-1) var(--size-3);
    align-items: baseline;
    margin: 0;
  }

  dt,
  dd {
    font-size: var(--font-size-1);
    margin: 0;
  }

  dt {
    color: var(--color-text-muted);
    font-weight: 500;
  }

  .external-ids {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }
</style>
