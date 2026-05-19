<script lang="ts">
  import Page from '$lib/components/Page.svelte';
  import Prose from '$lib/components/Prose.svelte';

  let { children } = $props();
</script>

<Page>
  <Prose>
    {@render children()}
  </Prose>
</Page>
