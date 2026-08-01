<!-- @component Person detail page: bio, details, media and the games listing pinned to the person with per-card roles. -->
<script lang="ts">
  import { ENTITY_META } from '$lib/entities/entity-meta';
  import AccordionSection from '$lib/components/ui/AccordionSection.svelte';
  import RichTextOverviewAccordion from '$lib/components/markdown/RichTextOverviewAccordion.svelte';
  import RichTextReferencesAccordion from '$lib/components/markdown/RichTextReferencesAccordion.svelte';
  import { createRichTextAccordionState } from '$lib/components/markdown/rich-text-accordion-state.svelte';
  import { personEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import MediaGrid from '$lib/components/media/MediaGrid.svelte';

  let { data } = $props();
  let person = $derived(data.profile);
  let editAction = personEditActionContext.get();
  const richTextState = createRichTextAccordionState();

  function formatDate(
    year: number | null | undefined,
    month: number | null | undefined,
    day: number | null | undefined,
  ): string | null {
    if (!year) return null;
    if (!month) return String(year);
    const monthName = new Date(year, month - 1).toLocaleString('en', { month: 'long' });
    if (!day) return `${monthName} ${year}`;
    return `${monthName} ${day}, ${year}`;
  }

  let birthDate = $derived(formatDate(person.birth_year, person.birth_month, person.birth_day));
  let deathDate = $derived(formatDate(person.death_year, person.death_month, person.death_day));
  let hasDetails = $derived(!!(birthDate || deathDate || person.birth_place || person.nationality));
  let mediaHeading = $derived(`Media (${person.uploaded_media.length})`);
</script>

{#if person.photo_url}
  <div class="photo">
    <img src={person.photo_url} alt={person.name} />
  </div>
{/if}

{#if person.description?.html}
  <RichTextOverviewAccordion
    richText={person.description}
    state={richTextState}
    heading="Bio"
    onEdit={editAction('bio')}
  />
{/if}

{#if hasDetails}
  <AccordionSection heading="Details" onEdit={editAction('details')}>
    <dl class="bio-meta">
      {#if person.nationality}
        <div class="bio-meta-row">
          <dt>Nationality</dt>
          <dd>{person.nationality}</dd>
        </div>
      {/if}
      {#if birthDate}
        <div class="bio-meta-row">
          <dt>Born</dt>
          <dd>
            {birthDate}{#if person.birth_place}, {person.birth_place}{/if}
          </dd>
        </div>
      {:else if person.birth_place}
        <div class="bio-meta-row">
          <dt>Birth place</dt>
          <dd>{person.birth_place}</dd>
        </div>
      {/if}
      {#if deathDate}
        <div class="bio-meta-row">
          <dt>Died</dt>
          <dd>{deathDate}</dd>
        </div>
      {/if}
    </dl>
  </AccordionSection>
{/if}

{#if person.uploaded_media.length > 0}
  <AccordionSection heading={mediaHeading} onEdit={editAction('media')}>
    <MediaGrid
      media={person.uploaded_media}
      categories={[...ENTITY_META.person.media_categories]}
      canEdit={false}
    />
  </AccordionSection>
{/if}

<RichTextReferencesAccordion richText={person.description} state={richTextState} />

<GamesSection games={person.games} q={data.q} />

<style>
  .photo {
    margin-bottom: var(--size-5);
  }

  .photo img {
    width: 160px;
    height: 160px;
    object-fit: cover;
    border-radius: var(--radius-3);
    display: block;
  }

  .bio-meta {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
    margin: 0;
  }

  .bio-meta-row {
    display: flex;
    gap: var(--size-3);
    font-size: var(--font-size-1);
  }

  .bio-meta dt {
    color: var(--color-text-muted);
    min-width: 7rem;
    flex-shrink: 0;
  }

  .bio-meta dd {
    color: var(--color-text);
    margin: 0;
  }
</style>
