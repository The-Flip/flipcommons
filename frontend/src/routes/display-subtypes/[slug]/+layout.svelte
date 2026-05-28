<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Display Types"
  basePath="/display-subtypes"
  parentHref="/display-types"
  claimsPath={'/api/display-subtypes/{public_id}/claims/'}
  deleteHref={`/display-subtypes/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
