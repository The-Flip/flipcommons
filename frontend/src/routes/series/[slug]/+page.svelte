<!-- @component Series detail page: description, the games listing pinned to the series and series-level credits. -->
<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import CreditsList from '$lib/components/pages/record/detail/CreditsList.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';

  let { data } = $props();
  let series = $derived(data.profile);
</script>

{#if series.description?.html}
  <section class="description">
    <Markdown html={series.description.html} citations={series.description.citations ?? []} />
    <AttributionLine attribution={series.description.attribution} />
  </section>
{/if}

<GamesSection games={series.games} q={data.q} pinned={{ series: series.slug }} />

<CreditsList credits={series.credits} />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
