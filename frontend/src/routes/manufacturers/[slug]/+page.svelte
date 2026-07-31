<!-- @component Manufacturer detail page: overview, companies, the games listing pinned to the manufacturer, systems, people and media. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import { ENTITY_META } from '$lib/entities/entity-meta';
  import AccordionSection from '$lib/components/ui/AccordionSection.svelte';
  import CreateFirstCorporateEntityPrompt from './_components/CreateFirstCorporateEntityPrompt.svelte';
  import RichTextOverviewAccordion from '$lib/components/markdown/RichTextOverviewAccordion.svelte';
  import RichTextReferencesAccordion from '$lib/components/markdown/RichTextReferencesAccordion.svelte';
  import { createRichTextAccordionState } from '$lib/components/markdown/rich-text-accordion-state.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import { manufacturerEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import LocationLink from '$lib/components/entity-links/LocationLink.svelte';
  import MediaGrid from '$lib/components/media/MediaGrid.svelte';
  import { formatActiveRange, websiteHostname } from '$lib/utils';

  let { data } = $props();
  let mfr = $derived(data.profile);
  let editAction = manufacturerEditActionContext.get();
  const richTextState = createRichTextAccordionState();

  let yearsActive = $derived(
    formatActiveRange(mfr.year_of_first_model, mfr.year_of_last_model, mfr.operating_status),
  );
  let hasCompanyDetails = $derived(!!(yearsActive || mfr.entities.length > 0 || mfr.website));
  let systemsHeading = $derived(`Systems (${mfr.systems.length})`);
  let peopleHeading = $derived(`People (${mfr.persons.length})`);
  let mediaHeading = $derived(`Media (${mfr.uploaded_media.length})`);
</script>

{#if mfr.description?.html}
  <RichTextOverviewAccordion
    richText={mfr.description}
    state={richTextState}
    onEdit={editAction('description')}
  />
{/if}

<!-- "Create first corporate entity" CTA when the manufacturer has no active
     entities. Shown to all viewers, mirroring Title's `CreateFirstModelPrompt`
     for create-flow discoverability. Anonymous users clicking through get
     bounced to login by the create page's load guard. -->
{#if mfr.entities.length === 0}
  <CreateFirstCorporateEntityPrompt manufacturerSlug={mfr.slug} manufacturerName={mfr.name} />
{/if}

{#if hasCompanyDetails}
  <AccordionSection heading="Companies">
    <div class="company-section">
      {#if yearsActive}
        <div class="detail-block">
          <h3>Years Active</h3>
          <p>{yearsActive}</p>
        </div>
      {/if}

      {#if mfr.entities.length > 0}
        <div class="detail-block">
          <h3>Companies</h3>
          <ul class="stack-list">
            {#each mfr.entities as entity (entity.public_id)}
              {@const activeRange = formatActiveRange(
                entity.year_of_first_model,
                entity.year_of_last_model,
                entity.operating_status,
              )}
              <li>
                <div class="entity">
                  <a href={resolve(`/corporate-entities/${entity.public_id}`)} class="entity-name"
                    >{entity.name}</a
                  >
                  {#if activeRange}
                    <span class="muted">{activeRange}</span>
                  {/if}
                  {#each entity.locations as loc, i (i)}
                    <LocationLink {loc} />
                  {/each}
                </div>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if mfr.website}
        <div class="detail-block">
          <h3>Website</h3>
          <p>
            <a href={mfr.website} target="_blank" rel="noopener">{websiteHostname(mfr.website)}</a>
          </p>
        </div>
      {/if}
    </div>
  </AccordionSection>
{/if}

<GamesSection
  games={mfr.games}
  q={data.q}
  pinned={{ manufacturer: mfr.slug }}
  showManufacturer={false}
/>

{#if mfr.systems.length > 0}
  <AccordionSection heading={systemsHeading}>
    <ul class="stack-list">
      {#each mfr.systems as system (system.public_id)}
        <li>
          <a href={resolve(`/systems/${system.public_id}`)}>{system.name}</a>
        </li>
      {/each}
    </ul>
  </AccordionSection>
{/if}

{#if mfr.persons.length > 0}
  <AccordionSection heading={peopleHeading}>
    <ul class="stack-list">
      {#each mfr.persons as person (person.public_id)}
        <li>
          <div class="entity">
            <a href={resolve(`/people/${person.public_id}`)}>{person.name}</a>
            {#if person.roles.length > 0}
              <span class="muted">{person.roles.join(', ')}</span>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  </AccordionSection>
{/if}

{#if mfr.uploaded_media.length > 0}
  <AccordionSection heading={mediaHeading}>
    <MediaGrid
      media={mfr.uploaded_media}
      categories={[...ENTITY_META.manufacturer.media_categories]}
      canEdit={false}
    />
  </AccordionSection>
{/if}

<RichTextReferencesAccordion richText={mfr.description} state={richTextState} />

<style>
  .company-section {
    display: flex;
    flex-direction: column;
    gap: var(--size-4);
  }

  .detail-block h3 {
    font-size: var(--font-size-1);
    margin: 0 0 var(--size-2);
  }

  .detail-block p {
    margin: 0;
  }

  .stack-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .entity {
    display: flex;
    flex-direction: column;
    gap: var(--size-00);
  }

  .entity-name {
    font-weight: 500;
    color: var(--color-text);
    text-decoration: none;
  }

  .entity-name:hover {
    color: var(--color-link);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }
</style>
