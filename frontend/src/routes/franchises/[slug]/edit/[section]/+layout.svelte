<script lang="ts">
  import SimpleTaxonomyEditSectionLayout from '$lib/components/pages/record/edit/SimpleTaxonomyEditSectionLayout.svelte';
  import { SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER } from '$lib/components/editors/simple-taxonomy-edit-sections';

  let { children } = $props();
</script>

<SimpleTaxonomyEditSectionLayout
  basePath="/franchises"
  sections={SIMPLE_TAXONOMY_EDIT_SECTIONS_NO_DISPLAY_ORDER}
>
  {@render children()}
</SimpleTaxonomyEditSectionLayout>
