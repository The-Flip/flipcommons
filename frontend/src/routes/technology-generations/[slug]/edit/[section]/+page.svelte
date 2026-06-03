<script lang="ts">
  import SimpleTaxonomyEditSectionPage from '$lib/components/pages/record/edit/SimpleTaxonomyEditSectionPage.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyEditSectionPage
  {profile}
  basePath="/technology-generations"
  claimsPath={'/api/technology-generations/{public_id}/claims/'}
/>
