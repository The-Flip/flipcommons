<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Tag"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/tags/', { body })}
  detailHref={(slug) => `/tags/${slug}`}
  cancelHref="/tags"
/>
