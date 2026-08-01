<!-- @component Reward-type detail page: description and the games listing pinned to the reward type. -->
<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);
</script>

{#if profile.description?.html}
  <section class="description">
    <Markdown html={profile.description.html} citations={profile.description.citations ?? []} />
    <AttributionLine attribution={profile.description.attribution} />
  </section>
{/if}

<GamesSection games={profile.games} q={data.q} />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
