<script lang="ts">
  import SimpleTaxonomyEditSectionPage from '$lib/components/SimpleTaxonomyEditSectionPage.svelte';
  import { SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER } from '$lib/components/editors/simple-taxonomy-edit-sections';

  let { data } = $props();
  let series = $derived(data.profile);
</script>

<SimpleTaxonomyEditSectionPage
  profile={series}
  basePath="/series"
  claimsPath={'/api/series/{public_id}/claims/'}
  sections={SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER}
/>
