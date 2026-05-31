<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/Markdown.svelte';
  import SearchableGrid from '$lib/components/grid/SearchableGrid.svelte';
  import PersonCard from '$lib/components/cards/PersonCard.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);
  let people = $derived(profile.people ?? []);
</script>

{#if profile.description?.html}
  <section class="description">
    <Markdown html={profile.description.html} citations={profile.description.citations ?? []} />
    <AttributionLine attribution={profile.description.attribution} />
  </section>
{/if}

<h2 class="section-heading">People With {profile.name} Credits</h2>
{#if people.length > 0}
  <SearchableGrid
    items={people}
    filterFields={(item) => [item.name, ...(item.aliases ?? [])]}
    placeholder="Search people credited with this role..."
    entityName="person"
    entityNamePlural={`people with ${profile.name} credits`}
  >
    {#snippet children(person)}
      <PersonCard
        slug={person.slug}
        name={person.name}
        thumbnailUrl={person.thumbnail_url}
        creditCount={person.credit_count}
        creditLabel={`${profile.name} credit`}
      />
    {/snippet}
  </SearchableGrid>
{:else}
  <p class="empty">No people credited in this role yet.</p>
{/if}

<style>
  .description {
    margin-bottom: var(--size-6);
  }

  .section-heading {
    font-size: var(--font-size-3);
    font-weight: 600;
    margin: 0 0 var(--size-3);
  }

  .empty {
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-6) 0;
    text-align: center;
  }
</style>
