<script lang="ts">
  import type { ModelDetailSchema } from '$lib/api/schema';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { ModelEditSectionKey } from './model-edit-sections';
  import BasicsEditor from './BasicsEditor.svelte';
  import DescriptionEditor from '$lib/components/pages/record/edit/editors/DescriptionEditor.svelte';
  import ExternalDataEditor from './ExternalDataEditor.svelte';
  import FeaturesEditor from './FeaturesEditor.svelte';
  import NameEditor from '$lib/components/pages/record/edit/editors/NameEditor.svelte';
  import PeopleEditor from './PeopleEditor.svelte';
  import RelatedModelsEditor from './RelatedModelsEditor.svelte';
  import { saveModelClaims } from './save-model-claims';
  import TechnologyEditor from './TechnologyEditor.svelte';

  type ModelDetail = ModelDetailSchema;

  let {
    sectionKey,
    initialData,
    slug,
    slim = false,
    editorRef = $bindable<SectionEditorHandle | undefined>(undefined),
    onsaved,
    onerror,
    ondirtychange,
  }: {
    sectionKey: ModelEditSectionKey;
    initialData: ModelDetail;
    slug: string;
    slim?: boolean;
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
    save={saveModelClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'basics'}
  <BasicsEditor
    bind:this={editorRef}
    {initialData}
    {slug}
    {slim}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'overview'}
  <DescriptionEditor
    bind:this={editorRef}
    initialData={initialData.description?.text ?? ''}
    {slug}
    save={saveModelClaims}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'technology'}
  <TechnologyEditor
    bind:this={editorRef}
    {initialData}
    {slug}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'features'}
  <FeaturesEditor bind:this={editorRef} {initialData} {slug} {onsaved} {onerror} {ondirtychange} />
{:else if sectionKey === 'people'}
  <PeopleEditor
    bind:this={editorRef}
    initialData={initialData.credits}
    {slug}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'related-models'}
  <RelatedModelsEditor
    bind:this={editorRef}
    {initialData}
    {slug}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{:else if sectionKey === 'external-data'}
  <ExternalDataEditor
    bind:this={editorRef}
    {initialData}
    {slug}
    {onsaved}
    {onerror}
    {ondirtychange}
  />
{/if}
