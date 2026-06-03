<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultManufacturerSectionSegment } from '$lib/components/pages/record/edit/editors/entity/manufacturer/manufacturer-edit-sections';
</script>

<EditRedirectFallback
  basePath="/manufacturers"
  defaultSegment={defaultManufacturerSectionSegment()}
/>
