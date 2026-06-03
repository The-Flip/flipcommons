<script lang="ts">
  import Page from '$lib/components/layout/page/Page.svelte';
  import Prose from '$lib/components/ui/Prose.svelte';

  let { children } = $props();
</script>

<Page>
  <Prose>
    {@render children()}
  </Prose>
</Page>
