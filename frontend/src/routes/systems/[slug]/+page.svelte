<!-- @component System detail page: description and the games listing pinned to the system. -->
<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';

  let { data } = $props();
  let system = $derived(data.profile);
</script>

{#if system.description?.html}
  <section class="description">
    <Markdown html={system.description.html} citations={system.description.citations ?? []} />
    <AttributionLine attribution={system.description.attribution} />
  </section>
{/if}

<GamesSection games={system.games} q={data.q} />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
