<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
  let parentSlug = $derived(data.parentSlug);
  let parentName = $derived(data.parentName);
</script>

<CreatePage
  entityLabel="Subtype"
  heading={`New subtype in ${parentName}`}
  initialName={data.initialName}
  submit={(body) =>
    client.POST('/api/display-types/{parent_public_id}/subtypes/', {
      params: { path: { parent_public_id: parentSlug } },
      body,
    })}
  detailHref={(slug) => `/display-subtypes/${slug}`}
  cancelHref={`/display-types/${parentSlug}`}
  parentBreadcrumb={{ text: parentName, href: `/display-types/${parentSlug}` }}
/>
