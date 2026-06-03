<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
  let parentSlug = $derived(data.parentSlug);
  let parentName = $derived(data.parentName);
</script>

<CreatePage
  entityLabel="Subgeneration"
  heading={`New subgeneration in ${parentName}`}
  initialName={data.initialName}
  submit={(body) =>
    client.POST('/api/technology-generations/{parent_public_id}/subgenerations/', {
      params: { path: { parent_public_id: parentSlug } },
      body,
    })}
  detailHref={(slug) => `/technology-subgenerations/${slug}`}
  cancelHref={`/technology-generations/${parentSlug}`}
  parentBreadcrumb={{ text: parentName, href: `/technology-generations/${parentSlug}` }}
/>
