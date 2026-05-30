<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Technology Generations"
  basePath="/technology-subgenerations"
  parentHref="/technology-generations"
  claimsPath={'/api/technology-subgenerations/{public_id}/claims/'}
  deleteHref={`/technology-subgenerations/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
