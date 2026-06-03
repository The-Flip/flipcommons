<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Manufacturer"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/manufacturers/', { body })}
  detailHref={(slug) => `/manufacturers/${slug}`}
  cancelHref="/manufacturers"
/>
