<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultSimpleTaxonomySectionSegment } from '$lib/components/pages/record/edit/editors/entity/taxonomy/simple-taxonomy-edit-sections';
</script>

<EditRedirectFallback basePath="/series" defaultSegment={defaultSimpleTaxonomySectionSegment()} />
