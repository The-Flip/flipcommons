<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Game Formats"
  basePath="/game-formats"
  claimsPath={'/api/game-formats/{public_id}/claims/'}
  deleteHref={`/game-formats/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
