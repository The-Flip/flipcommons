<script lang="ts">
  import client from '$lib/api/client';
  import type { SystemCreateSchema } from '$lib/api/schema';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';

  type CreateBody = SystemCreateSchema;

  let { data } = $props();

  let manufacturerSlug = $state<string | null>(null);

  function buildExtraBody() {
    if (!manufacturerSlug) {
      return { error: 'Manufacturer is required.' };
    }
    return { manufacturer_slug: manufacturerSlug };
  }
</script>

<CreatePage
  entityLabel="System"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/systems/', { body: body as CreateBody })}
  detailHref={(slug) => `/systems/${slug}`}
  cancelHref="/systems"
  extraFieldKeys={['manufacturer_slug']}
  extraBody={buildExtraBody}
>
  {#snippet extraFields({ errors })}
    <EntitySelect
      type="manufacturer"
      label="Manufacturer"
      bind:selected={manufacturerSlug}
      error={errors.manufacturer_slug ?? ''}
      placeholder="Search manufacturers..."
      required
    />
  {/snippet}
</CreatePage>
