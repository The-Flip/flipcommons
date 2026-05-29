<script lang="ts">
  import Layout from './+layout.svelte';
  import type { LayoutData } from './$types';

  // `jsonLd` is optional here so content-focused tests can pass just `profile`;
  // the layout guards on `{#if data.jsonLd}`, so undefined renders nothing.
  let {
    data,
    childText = 'Child content',
  }: { data: Omit<LayoutData, 'jsonLd'> & { jsonLd?: LayoutData['jsonLd'] }; childText?: string } =
    $props();
</script>

<Layout data={data as LayoutData}>
  <p>{childText}</p>
</Layout>
