<script lang="ts">
  import TaxonomyEditSectionPageBase from './TaxonomyEditSectionPageBase.svelte';
  import {
    defaultSimpleTaxonomySectionSegment,
    SIMPLE_TAXONOMY_EDIT_SECTIONS,
    type SimpleTaxonomyEditSectionDef,
    type SimpleTaxonomyEditSectionKey,
  } from '$lib/components/pages/record/edit/editors/entity/taxonomy/simple-taxonomy-edit-sections';
  import SimpleTaxonomyEditorSwitch from '$lib/components/pages/record/edit/editors/entity/taxonomy/SimpleTaxonomyEditorSwitch.svelte';
  import type { SimpleTaxonomyClaimsPath } from '$lib/components/pages/record/edit/editors/save-claims-shared';
  import type { SimpleTaxonomyEditView } from '$lib/components/pages/record/edit/editors/entity/taxonomy/simple-taxonomy-edit-types';

  let {
    profile,
    basePath,
    claimsPath,
    sections: sectionsProp = SIMPLE_TAXONOMY_EDIT_SECTIONS,
  }: {
    profile: SimpleTaxonomyEditView;
    basePath: string;
    claimsPath: SimpleTaxonomyClaimsPath;
    sections?: SimpleTaxonomyEditSectionDef[];
  } = $props();

  let sections = $derived(
    sectionsProp.map((section) => ({ ...section, usesSectionEditorForm: true })),
  );
</script>

<TaxonomyEditSectionPageBase
  {basePath}
  {sections}
  defaultSegment={defaultSimpleTaxonomySectionSegment()}
>
  {#snippet editor(key: SimpleTaxonomyEditSectionKey, { ref, onsaved, onerror, ondirtychange })}
    <SimpleTaxonomyEditorSwitch
      sectionKey={key}
      initialData={profile}
      slug={profile.slug}
      {claimsPath}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
      {ondirtychange}
    />
  {/snippet}
</TaxonomyEditSectionPageBase>
