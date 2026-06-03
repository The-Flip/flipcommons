<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/pages/record/detail/SimpleTaxonomyDetailLayout.svelte';

  let { data, children } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Tags"
  basePath="/tags"
  claimsPath={'/api/tags/{public_id}/claims/'}
  deleteHref={`/tags/${profile.slug}/delete`}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
