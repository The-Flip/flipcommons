<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Gameplay Feature"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/gameplay-features/', { body })}
  detailHref={(slug) => `/gameplay-features/${slug}`}
  cancelHref="/gameplay-features"
/>
