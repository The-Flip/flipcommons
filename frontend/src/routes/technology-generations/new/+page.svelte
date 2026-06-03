<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Technology Generation"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/technology-generations/', { body })}
  detailHref={(slug) => `/technology-generations/${slug}`}
  cancelHref="/technology-generations"
/>
