<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Cabinet"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/cabinets/', { body })}
  detailHref={(slug) => `/cabinets/${slug}`}
  cancelHref="/cabinets"
/>
