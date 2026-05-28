<script lang="ts">
  import HierarchicalTaxonomyChildrenAccordion from './HierarchicalTaxonomyChildrenAccordion.svelte';

  let {
    basePath = '/gameplay-features',
    children = [
      { name: 'Slingshot', public_id: 'slingshot' },
      { name: 'Bumper', public_id: 'bumper' },
    ],
    heading = 'Subtypes',
  }: {
    basePath?: string;
    children?: { name: string; public_id: string }[];
    heading?: string;
  } = $props();
</script>

<HierarchicalTaxonomyChildrenAccordion {basePath} {children} {heading} />
