<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultCorporateEntitySectionSegment } from '$lib/components/editors/corporate-entity-edit-sections';
</script>

<EditRedirectFallback
  basePath="/corporate-entities"
  defaultSegment={defaultCorporateEntitySectionSegment()}
/>
