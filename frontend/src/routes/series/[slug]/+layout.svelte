<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/pages/record/detail/SimpleTaxonomyDetailLayout.svelte';
  import { SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER } from '$lib/components/editors/simple-taxonomy-edit-sections';

  let { data, children } = $props();
  let series = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  profile={series}
  jsonLd={data.jsonLd}
  parentLabel="Series"
  basePath="/series"
  claimsPath={'/api/series/{public_id}/claims/'}
  deleteHref={`/series/${series.slug}/delete`}
  sections={SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
