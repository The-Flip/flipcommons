<script lang="ts">
  import SimpleTaxonomyEditSectionPage from '$lib/components/pages/record/edit/SimpleTaxonomyEditSectionPage.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyEditSectionPage
  {profile}
  basePath="/display-subtypes"
  claimsPath={'/api/display-subtypes/{public_id}/claims/'}
/>
