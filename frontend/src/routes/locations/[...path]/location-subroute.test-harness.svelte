<!--
	Renders a location sub-route page inside the real `+layout.svelte`, the way
	SvelteKit nests them, so a test exercises the context the layout publishes to
	its descendants rather than a stand-in. Test-only — do not import from
	production code.
-->
<script lang="ts">
  import Layout from './+layout.svelte';
  import EditHistoryPage from './edit-history/+page.svelte';

  let { data, pageData } = $props();
</script>

<Layout {data}>
  <EditHistoryPage data={pageData} />
</Layout>
