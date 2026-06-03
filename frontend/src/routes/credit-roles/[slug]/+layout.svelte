<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/pages/record/detail/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Credit Roles"
  basePath="/credit-roles"
  claimsPath={'/api/credit-roles/{public_id}/claims/'}
  deleteHref={`/credit-roles/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
