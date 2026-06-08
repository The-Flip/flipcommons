<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/pages/record/detail/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Production statuses"
  basePath="/production-statuses"
  claimsPath={'/api/production-statuses/{public_id}/claims/'}
  deleteHref={`/production-statuses/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
