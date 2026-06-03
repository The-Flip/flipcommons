<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultPersonSectionSegment } from '$lib/components/editors/person-edit-sections';
</script>

<EditRedirectFallback basePath="/people" defaultSegment={defaultPersonSectionSegment()} />
