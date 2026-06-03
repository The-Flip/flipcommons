<script lang="ts">
  import Page from '$lib/components/layout/page/Page.svelte';

  let { children } = $props();
</script>

<Page>
  {@render children()}
</Page>
