<!-- @component Franchise detail page: description and the games listing pinned to the franchise. -->
<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';

  let { data } = $props();
  let franchise = $derived(data.profile);
</script>

{#if franchise.description?.html}
  <section class="description">
    <Markdown html={franchise.description.html} citations={franchise.description.citations ?? []} />
    <AttributionLine attribution={franchise.description.attribution} />
  </section>
{/if}

<GamesSection games={franchise.games} q={data.q} />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
