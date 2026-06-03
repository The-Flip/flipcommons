<script lang="ts">
  import client from '$lib/api/client';
  import type { LocationTopLevelCreateSchema } from '$lib/api/schema';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';
  import TagInput from '$lib/components/input/TagInput.svelte';

  type CreateBody = LocationTopLevelCreateSchema;

  let { data } = $props();

  let divisions = $state<string[]>([]);

  function buildExtraBody() {
    if (divisions.length === 0) {
      return { error: 'Add at least one division (e.g. state, city).' };
    }
    return { divisions };
  }
</script>

<CreatePage
  entityLabel="Country"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/locations/', { body: body as CreateBody })}
  detailHref={(slug) => `/locations/${slug}`}
  cancelHref="/locations"
  extraFieldKeys={['divisions']}
  extraBody={buildExtraBody}
  parentBreadcrumb={{ text: 'Locations', href: '/locations' }}
>
  {#snippet extraFields({ errors })}
    <div class="divisions-field">
      <TagInput
        label="Divisions"
        bind:tags={divisions}
        placeholder="state, city — press Enter after each"
        error={errors.divisions ?? ''}
      />
      <p class="hint">
        Labels for child tiers, ordered from country down. The first label names the next tier of
        children under this country (e.g. <code>state</code> for the USA, <code>region</code> for France).
      </p>
    </div>
  {/snippet}
</CreatePage>

<style>
  .divisions-field {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }
  .hint {
    margin: 0;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }
</style>
