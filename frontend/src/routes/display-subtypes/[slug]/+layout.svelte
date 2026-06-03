<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/SimpleTaxonomyDetailLayout.svelte';
  import { listingMeta } from '$lib/entities/schema-org';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel={listingMeta('display-type').breadcrumb}
  basePath="/display-subtypes"
  breadcrumbs={[
    { label: listingMeta('display-type').breadcrumb, href: '/display-types' },
    {
      label: profile.display_type.name,
      href: `/display-types/${profile.display_type.public_id}`,
    },
  ]}
  claimsPath={'/api/display-subtypes/{public_id}/claims/'}
  deleteHref={`/display-subtypes/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
