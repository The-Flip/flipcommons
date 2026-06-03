<script lang="ts">
  import client from '$lib/api/client';
  import type { SystemCreateSchema } from '$lib/api/schema';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import {
    fetchManufacturerOptions,
    type SystemEditOption,
  } from '$lib/components/editors/system-edit-options';

  type CreateBody = SystemCreateSchema;

  let { data } = $props();

  let manufacturerOptions = $state<SystemEditOption[]>([]);
  let manufacturerSlug = $state<string | null>(null);

  $effect(() => {
    fetchManufacturerOptions().then((opts) => (manufacturerOptions = opts));
  });

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
    <SearchableSelect
      label="Manufacturer"
      options={manufacturerOptions}
      bind:selected={manufacturerSlug}
      error={errors.manufacturer_slug ?? ''}
      allowZeroCount
      showCounts={false}
      placeholder="Search manufacturers..."
    />
  {/snippet}
</CreatePage>
