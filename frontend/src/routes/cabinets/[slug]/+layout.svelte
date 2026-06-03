<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/pages/record/detail/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Cabinets"
  basePath="/cabinets"
  claimsPath={'/api/cabinets/{public_id}/claims/'}
  deleteHref={`/cabinets/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
