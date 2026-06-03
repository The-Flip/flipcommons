<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Game Format"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/game-formats/', { body })}
  detailHref={(slug) => `/game-formats/${slug}`}
  cancelHref="/game-formats"
/>
