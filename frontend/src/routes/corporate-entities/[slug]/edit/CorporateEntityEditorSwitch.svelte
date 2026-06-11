<script lang="ts">
  import AliasesSectionEditor from '$lib/components/pages/record/edit/editors/AliasesSectionEditor.svelte';
  import DescriptionEditor from '$lib/components/pages/record/edit/editors/DescriptionEditor.svelte';
  import NameEditor from '$lib/components/pages/record/edit/editors/NameEditor.svelte';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { CorporateEntityEditSectionKey } from '$lib/components/pages/record/edit/editors/entity/corporate-entity/corporate-entity-edit-sections';
  import { saveCorporateEntityClaims } from './save-corporate-entity-claims';
  import type { CorporateEntityEditView } from './corporate-entity-edit-types';

  let {
    sectionKey,
    initialData,
    slug,
    editorRef = $bindable<SectionEditorHandle | undefined>(undefined),
    onsaved,
    onerror,
    ondirtychange,
  }: {
    sectionKey: CorporateEntityEditSectionKey;
    initialData: CorporateEntityEditView;
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
    {slug}
    save={saveCorporateEntityClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'description'}
  <DescriptionEditor
    bind:this={editorRef}
    initialData={initialData.description?.text ?? ''}
    {slug}
    save={saveCorporateEntityClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'aliases'}
  <AliasesSectionEditor
    bind:this={editorRef}
    initialData={{ aliases: initialData.aliases }}
    {slug}
    save={saveCorporateEntityClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{/if}
