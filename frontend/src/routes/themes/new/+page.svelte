<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Theme"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/themes/', { body })}
  detailHref={(slug) => `/themes/${slug}`}
  cancelHref="/themes"
/>
