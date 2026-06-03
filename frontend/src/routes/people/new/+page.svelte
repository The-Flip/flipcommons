<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Person"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/people/', { body })}
  detailHref={(slug) => `/people/${slug}`}
  cancelHref="/people"
/>
