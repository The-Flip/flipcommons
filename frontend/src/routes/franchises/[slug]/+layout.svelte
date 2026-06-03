<script lang="ts">
  import SimpleTaxonomyDetailLayout from '$lib/components/pages/record/detail/SimpleTaxonomyDetailLayout.svelte';
  import { SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER } from '$lib/components/editors/simple-taxonomy-edit-sections';

  let { data, children } = $props();
  let franchise = $derived(data.profile);
</script>

<SimpleTaxonomyDetailLayout
  profile={franchise}
  jsonLd={data.jsonLd}
  parentLabel="Franchises"
  basePath="/franchises"
  claimsPath={'/api/franchises/{public_id}/claims/'}
  deleteHref={`/franchises/${franchise.slug}/delete`}
  sections={SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER}
>
  {@render children()}
</SimpleTaxonomyDetailLayout>
