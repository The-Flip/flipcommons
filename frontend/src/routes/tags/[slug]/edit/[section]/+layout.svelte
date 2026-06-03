<script lang="ts">
  import SimpleTaxonomyEditSectionLayout from '$lib/components/pages/record/edit/SimpleTaxonomyEditSectionLayout.svelte';

  let { children } = $props();
</script>

<SimpleTaxonomyEditSectionLayout basePath="/tags">
  {@render children()}
</SimpleTaxonomyEditSectionLayout>
