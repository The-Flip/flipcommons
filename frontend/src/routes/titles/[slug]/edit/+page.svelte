<script lang="ts">
  import EditRedirectFallback from '$lib/components/pages/record/edit/EditRedirectFallback.svelte';
  import { defaultTitleSectionSegment } from '$lib/components/pages/record/edit/editors/entity/title/title-edit-sections';

  let { data } = $props();
  let isSingleModel = $derived(!!data.profile.model_detail);
  let defaultSegment = $derived(defaultTitleSectionSegment(isSingleModel));
</script>

<EditRedirectFallback basePath="/titles" {defaultSegment} />
