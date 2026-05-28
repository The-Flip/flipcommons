<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Technology Generations"
  basePath="/technology-generations"
  claimsPath={'/api/technology-generations/{public_id}/claims/'}
  deleteHref={`/technology-generations/${profile.slug}/delete`}
  createChild={{
    href: `/technology-subgenerations/new?parent=${profile.slug}`,
    label: 'subgeneration',
  }}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
