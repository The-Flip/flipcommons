<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';

  let { data } = $props();
</script>

<CreatePage
  entityLabel="Credit Role"
  initialName={data.initialName}
  submit={(body) => client.POST('/api/credit-roles/', { body })}
  detailHref={(slug) => `/credit-roles/${slug}`}
  cancelHref="/credit-roles"
/>
