<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Series"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/series/', { body })}
  detailHref={(slug) => `/series/${slug}`}
  cancelHref="/series"
/>
