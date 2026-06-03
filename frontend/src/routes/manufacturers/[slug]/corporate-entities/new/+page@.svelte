<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Corporate Entity"
  initialName={data.initialName}
  submit={(body) =>
    client.POST('/api/manufacturers/{parent_public_id}/corporate-entities/', {
      params: { path: { parent_public_id: data.manufacturer.slug } },
      body,
    })}
  detailHref={(slug) => `/corporate-entities/${slug}`}
  cancelHref={`/manufacturers/${data.manufacturer.slug}`}
  parentBreadcrumb={{
    text: data.manufacturer.name,
    href: `/manufacturers/${data.manufacturer.slug}`,
  }}
/>
