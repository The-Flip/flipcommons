<script lang="ts">
  import SimpleTaxonomyEditSectionPage from '$lib/components/pages/record/edit/SimpleTaxonomyEditSectionPage.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);
</script>

<SimpleTaxonomyEditSectionPage
  {profile}
  basePath="/tags"
  claimsPath={'/api/tags/{public_id}/claims/'}
/>
