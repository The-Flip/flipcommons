<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Display Types"
  basePath="/display-types"
  claimsPath={'/api/display-types/{public_id}/claims/'}
  deleteHref={`/display-types/${profile.slug}/delete`}
  createChild={{
    href: `/display-subtypes/new?parent=${profile.slug}`,
    label: 'subtype',
  }}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
