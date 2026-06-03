<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';
  import { childLabelFor } from '../location-helpers';
  import type { LocationDetailSchema } from '$lib/api/schema';

  let { data } = $props();
  let profile = $derived<LocationDetailSchema>(data.profile);
  let parentPath = $derived(profile.public_id);
  let expected = $derived(profile.expected_child_type);
  let entityLabel = $derived(expected ? childLabelFor(expected) : 'Location');
</script>

{#if expected}
  <CreatePage
    {entityLabel}
    initialName={data.initialName}
    submit={(body) =>
      client.POST('/api/locations/{parent_public_id}/children/', {
        params: { path: { parent_public_id: parentPath } },
        body,
      })}
    detailHref={(slug) => `/locations/${parentPath}/${slug}`}
    cancelHref={`/locations/${parentPath}`}
    parentBreadcrumb={{ text: profile.name, href: `/locations/${parentPath}` }}
  />
{:else}
  <p class="empty">This location can't have child locations.</p>
{/if}

<style>
  .empty {
    max-width: 36rem;
    margin: var(--size-6) auto;
    padding: 0 var(--size-5);
  }
</style>
