<script lang="ts">
  import Layout from './+layout.svelte';
  import type { LayoutData } from './$types';

  let { data, childText = 'Child content' }: { data: LayoutData; childText?: string } = $props();
</script>

<Layout {data}>
  <p>{childText}</p>
</Layout>
