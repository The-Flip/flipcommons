<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Reward Type"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/reward-types/', { body })}
  detailHref={(slug) => `/reward-types/${slug}`}
  cancelHref="/reward-types"
/>
