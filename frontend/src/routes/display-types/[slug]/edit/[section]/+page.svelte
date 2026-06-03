<script lang="ts">
  import SimpleTaxonomyEditSectionPage from '$lib/components/pages/record/edit/SimpleTaxonomyEditSectionPage.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyEditSectionPage
  {profile}
  basePath="/display-types"
  claimsPath={'/api/display-types/{public_id}/claims/'}
/>
