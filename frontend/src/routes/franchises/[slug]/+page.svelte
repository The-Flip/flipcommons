<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/Markdown.svelte';
  import TitleList from '$lib/components/TitleList.svelte';

  let { data } = $props();
  let franchise = $derived(data.profile);
</script>

{#if franchise.description?.html}
  <section class="description">
    <Markdown html={franchise.description.html} citations={franchise.description.citations ?? []} />
    <AttributionLine attribution={franchise.description.attribution} />
  </section>
{/if}

<TitleList titles={franchise.titles} emptyMessage="No titles in this franchise." />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
