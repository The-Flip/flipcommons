<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/SimpleTaxonomyDetailLayout.svelte';
  import { listingMeta } from '$lib/entities/schema-org';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel={listingMeta('technology-generation').breadcrumb}
  basePath="/technology-subgenerations"
  breadcrumbs={[
    { label: listingMeta('technology-generation').breadcrumb, href: '/technology-generations' },
    {
      label: profile.technology_generation.name,
      href: `/technology-generations/${profile.technology_generation.public_id}`,
    },
  ]}
  claimsPath={'/api/technology-subgenerations/{public_id}/claims/'}
  deleteHref={`/technology-subgenerations/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
