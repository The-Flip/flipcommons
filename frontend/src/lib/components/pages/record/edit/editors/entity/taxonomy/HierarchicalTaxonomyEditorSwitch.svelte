<script lang="ts">
  import AliasesSectionEditor from '$lib/components/pages/record/edit/editors/AliasesSectionEditor.svelte';
  import DescriptionEditor from '$lib/components/pages/record/edit/editors/DescriptionEditor.svelte';
  import NameEditor from '$lib/components/pages/record/edit/editors/NameEditor.svelte';
  import ParentsSectionEditor from './ParentsSectionEditor.svelte';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { HierarchicalTaxonomyEditSectionKey } from './hierarchical-taxonomy-edit-sections';
  import type { HierarchicalTaxonomyEditView } from './hierarchical-taxonomy-edit-types';
  import {
    saveHierarchicalTaxonomyClaims,
    type HierarchicalTaxonomyClaimsPath,
    type HierarchicalTaxonomySectionPatchBody,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';

  type ParentOption = { slug: string; label: string; count?: number };
  type ParentOptionsLoader = () => Promise<ParentOption[]>;

  let {
    sectionKey,
    initialData,
    slug,
    claimsPath,
    parentOptionsLoader,
    parentsLabel,
    editorRef = $bindable<SectionEditorHandle | undefined>(undefined),
    onsaved,
    onerror,
    ondirtychange,
  }: {
    sectionKey: HierarchicalTaxonomyEditSectionKey;
    initialData: HierarchicalTaxonomyEditView;
    slug: string;
    claimsPath: HierarchicalTaxonomyClaimsPath;
    parentOptionsLoader: ParentOptionsLoader;
    /** Field label for the parents picker (e.g. "This feature is a type of..."). Defaults to ParentsSectionEditor's default. */
    parentsLabel?: string;
    editorRef?: SectionEditorHandle | undefined;
    onsaved: () => void;
    onerror: (message: string) => void;
    ondirtychange: (dirty: boolean) => void;
  } = $props();

  const saveClaims = (s: string, body: HierarchicalTaxonomySectionPatchBody) =>
    saveHierarchicalTaxonomyClaims(claimsPath, s, body);
</script>

{#if sectionKey === 'name'}
  <NameEditor
    bind:this={editorRef}
    initialData={{ name: initialData.name, slug: initialData.slug }}
    {slug}
    save={saveClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'description'}
  <DescriptionEditor
    bind:this={editorRef}
    initialData={initialData.description.text}
    {slug}
    save={saveClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'aliases'}
  <AliasesSectionEditor
    bind:this={editorRef}
    initialData={{ aliases: initialData.aliases }}
    {slug}
    save={saveClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'parents'}
  <ParentsSectionEditor
    bind:this={editorRef}
    initialData={{ parents: initialData.parents }}
    {slug}
    save={saveClaims}
    optionsLoader={parentOptionsLoader}
    label={parentsLabel}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{/if}
