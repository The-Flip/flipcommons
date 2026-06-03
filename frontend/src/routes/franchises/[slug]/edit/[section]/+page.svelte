<script lang="ts">
  import SimpleTaxonomyEditSectionPage from '$lib/components/pages/record/edit/SimpleTaxonomyEditSectionPage.svelte';
  import { SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER } from '$lib/components/pages/record/edit/editors/entity/taxonomy/simple-taxonomy-edit-sections';

  let { data } = $props();
  let franchise = $derived(data.profile);
</script>

<SimpleTaxonomyEditSectionPage
  profile={franchise}
  basePath="/franchises"
  claimsPath={'/api/franchises/{public_id}/claims/'}
  sections={SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER}
/>
