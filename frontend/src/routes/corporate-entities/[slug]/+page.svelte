<!-- @component Corporate-entity detail page: description and the games listing pinned to the corporate entity. -->
<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';

  let { data } = $props();
  let ce = $derived(data.profile);
</script>

{#if ce.description?.html}
  <div class="description">
    <Markdown html={ce.description.html} citations={ce.description.citations} />
    <AttributionLine attribution={ce.description.attribution} />
  </div>
{/if}

<GamesSection
  games={ce.games}
  q={data.q}
  pinned={{ corporate_entity: ce.slug }}
  showManufacturer={false}
/>

<style>
  .description {
    margin-bottom: var(--size-5);
  }
</style>
