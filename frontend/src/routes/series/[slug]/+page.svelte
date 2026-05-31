<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import CreditsList from '$lib/components/CreditsList.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import TitleList from '$lib/components/TitleList.svelte';

  let { data } = $props();
  let series = $derived(data.profile);
</script>

{#if series.description?.html}
  <section class="description">
    <Markdown html={series.description.html} citations={series.description.citations ?? []} />
    <AttributionLine attribution={series.description.attribution} />
  </section>
{/if}

<TitleList titles={series.titles} emptyMessage="No titles in this series." />

<CreditsList credits={series.credits} />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
