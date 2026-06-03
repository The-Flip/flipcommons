<script lang="ts">
  import { page } from '$app/state';
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultLocationSectionSegment } from '$lib/components/editors/location-edit-sections';

  let path = $derived(page.params.path);
</script>

<EditRedirectFallback
  basePath="/locations"
  defaultSegment={defaultLocationSectionSegment()}
  publicId={path}
/>
