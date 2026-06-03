<script lang="ts">
  import type { TitleDetailSchema } from '$lib/api/schema';
  import DescriptionEditor from '$lib/components/pages/record/edit/editors/DescriptionEditor.svelte';
  import NameEditor from '$lib/components/pages/record/edit/editors/NameEditor.svelte';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { saveTitleClaims } from '$lib/components/pages/record/edit/editors/entity/title/save-title-claims';
  import type { TitleEditSectionKey } from '$lib/components/pages/record/edit/editors/entity/title/title-edit-sections';
  import TitleFranchiseEditor from '$lib/components/pages/record/edit/editors/entity/title/TitleFranchiseEditor.svelte';
  import TitleExternalDataEditor from '$lib/components/pages/record/edit/editors/entity/title/TitleExternalDataEditor.svelte';

  type TitleDetail = TitleDetailSchema;

  let {
    sectionKey,
    initialData,
    slug,
    editorRef = $bindable<SectionEditorHandle | undefined>(undefined),
    onsaved,
    onerror,
    ondirtychange,
  }: {
    sectionKey: TitleEditSectionKey;
    initialData: TitleDetail;
    slug: string;
    editorRef?: SectionEditorHandle | undefined;
    onsaved: () => void;
    onerror: (message: string) => void;
    ondirtychange: (dirty: boolean) => void;
  } = $props();
</script>

{#if sectionKey === 'name'}
  <NameEditor
    bind:this={editorRef}
    initialData={{ name: initialData.name, slug: initialData.slug }}
    initialAbbreviations={initialData.abbreviations}
    {slug}
    save={saveTitleClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'overview'}
  <DescriptionEditor
    bind:this={editorRef}
    initialData={initialData.description?.text ?? ''}
    {slug}
    save={saveTitleClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'franchise'}
  <TitleFranchiseEditor
    bind:this={editorRef}
    {initialData}
    {slug}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'external-data'}
  <TitleExternalDataEditor
    bind:this={editorRef}
    {initialData}
    {slug}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{/if}
