<script lang="ts">
  import type { Snippet } from 'svelte';
  import TaxonomyEditSectionLayoutBase from './TaxonomyEditSectionLayoutBase.svelte';
  import {
    defaultSimpleTaxonomySectionSegment,
    SIMPLE_TAXONOMY_EDIT_SECTIONS,
    type SimpleTaxonomyEditSectionDef,
  } from '$lib/components/editors/simple-taxonomy-edit-sections';

  let {
    basePath,
    sections = SIMPLE_TAXONOMY_EDIT_SECTIONS,
    children,
  }: {
    basePath: string;
    sections?: SimpleTaxonomyEditSectionDef[];
    children: Snippet;
  } = $props();
</script>

<TaxonomyEditSectionLayoutBase
  {basePath}
  {sections}
  defaultSegment={defaultSimpleTaxonomySectionSegment()}
>
  {@render children()}
</TaxonomyEditSectionLayoutBase>
