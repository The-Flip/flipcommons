<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultSimpleTaxonomySectionSegment } from '$lib/components/editors/simple-taxonomy-edit-sections';
</script>

<EditRedirectFallback basePath="/tags" defaultSegment={defaultSimpleTaxonomySectionSegment()} />
