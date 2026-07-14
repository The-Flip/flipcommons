<script lang="ts">
  import DescriptionEditor from '$lib/components/pages/record/edit/editors/DescriptionEditor.svelte';
  import NameEditor from '$lib/components/pages/record/edit/editors/NameEditor.svelte';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { ManufacturerEditSectionKey } from '$lib/components/pages/record/edit/editors/entity/manufacturer/manufacturer-edit-sections';
  import ManufacturerBasicsEditor from './ManufacturerBasicsEditor.svelte';
  import { saveManufacturerClaims } from './save-manufacturer-claims';
  import type { ManufacturerEditView } from './manufacturer-edit-types';

  let {
    sectionKey,
    initialData,
    slug,
    editorRef = $bindable<SectionEditorHandle | undefined>(undefined),
    onsaved,
    onerror,
  }: {
    sectionKey: ManufacturerEditSectionKey;
    initialData: ManufacturerEditView;
    slug: string;
    editorRef?: SectionEditorHandle | undefined;
    onsaved: () => void;
    onerror: (message: string) => void;
  } = $props();
</script>

{#if sectionKey === 'name'}
  <NameEditor
    bind:this={editorRef}
    initialData={{ name: initialData.name, slug: initialData.slug }}
    {slug}
    save={saveManufacturerClaims}
    {onsaved}
    {onerror}
  />
{:else if sectionKey === 'description'}
  <DescriptionEditor
    bind:this={editorRef}
    initialData={initialData.description?.text ?? ''}
    {slug}
    save={saveManufacturerClaims}
    {onsaved}
    {onerror}
  />
{:else if sectionKey === 'basics'}
  <ManufacturerBasicsEditor bind:this={editorRef} {initialData} {slug} {onsaved} {onerror} />
{/if}
