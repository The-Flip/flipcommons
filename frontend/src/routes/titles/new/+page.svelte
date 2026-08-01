<script lang="ts">
  import { resolve } from '$app/paths';
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Title"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/titles/', { body })}
  detailHref={(slug) => `/titles/${slug}`}
  cancelHref={resolve('/games')}
/>
