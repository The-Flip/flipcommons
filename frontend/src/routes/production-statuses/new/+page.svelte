<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Production status"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/production-statuses/', { body })}
  detailHref={(slug) => `/production-statuses/${slug}`}
  cancelHref="/production-statuses"
/>
