<script lang="ts">
  import EditHistory from '$lib/components/pages/record/edit-history/EditHistory.svelte';

  let { data } = $props();
</script>

<EditHistory changesets={data.changesets} />
