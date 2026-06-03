<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Display Type"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/display-types/', { body })}
  detailHref={(slug) => `/display-types/${slug}`}
  cancelHref="/display-types"
/>
