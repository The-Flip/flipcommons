<script lang="ts">
  import Page from '$lib/components/Page.svelte';

  let { children } = $props();
</script>

<Page>
  {@render children()}
</Page>
