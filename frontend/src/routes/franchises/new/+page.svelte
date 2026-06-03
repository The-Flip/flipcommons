<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Franchise"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/franchises/', { body })}
  detailHref={(slug) => `/franchises/${slug}`}
  cancelHref="/franchises"
/>
