<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/pages/record/detail/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Reward Types"
  basePath="/reward-types"
  claimsPath={'/api/reward-types/{public_id}/claims/'}
  deleteHref={`/reward-types/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
