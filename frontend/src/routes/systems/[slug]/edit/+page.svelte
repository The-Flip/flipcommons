<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultSystemSectionSegment } from '$lib/components/pages/record/edit/editors/entity/system/system-edit-sections';
</script>

<EditRedirectFallback basePath="/systems" defaultSegment={defaultSystemSectionSegment()} />
