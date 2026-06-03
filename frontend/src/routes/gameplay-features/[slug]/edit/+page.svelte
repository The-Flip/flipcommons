<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultHierarchicalTaxonomySectionSegment } from '$lib/components/pages/record/edit/editors/entity/taxonomy/hierarchical-taxonomy-edit-sections';
</script>

<EditRedirectFallback
  basePath="/gameplay-features"
  defaultSegment={defaultHierarchicalTaxonomySectionSegment()}
/>
