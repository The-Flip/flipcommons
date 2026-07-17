<script lang="ts">
  import AliasesSectionEditor from '$lib/components/pages/record/edit/editors/AliasesSectionEditor.svelte';
  import DescriptionEditor from '$lib/components/pages/record/edit/editors/DescriptionEditor.svelte';
  import type { SectionEditorHandle } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { LocationEditSectionKey } from '$lib/components/pages/record/edit/editors/entity/location/location-edit-sections';
  import LocationBasicsEditor from './LocationBasicsEditor.svelte';
  import LocationDivisionsEditor from './LocationDivisionsEditor.svelte';
  import { saveLocationClaims } from './save-location-claims';
  import type { LocationEditView } from './location-edit-types';

  let {
    sectionKey,
    initialData,
    publicId,
    editorRef = $bindable<SectionEditorHandle | undefined>(undefined),
    onsaved,
    onerror,
  }: {
    sectionKey: LocationEditSectionKey;
    initialData: LocationEditView;
    publicId: string;
    editorRef?: SectionEditorHandle | undefined;
    onsaved: () => void;
    onerror: (message: string) => void;
  } = $props();
</script>

{#if sectionKey === 'description'}
  <DescriptionEditor
    bind:this={editorRef}
    initialData={initialData.description?.text ?? ''}
    slug={publicId}
    save={saveLocationClaims}
    {onsaved}
    {onerror}
  />
{:else if sectionKey === 'basics'}
  <LocationBasicsEditor bind:this={editorRef} {initialData} slug={publicId} {onsaved} {onerror} />
{:else if sectionKey === 'divisions'}
  <LocationDivisionsEditor
    bind:this={editorRef}
    {initialData}
    slug={publicId}
    {onsaved}
    {onerror}
  />
{:else if sectionKey === 'aliases'}
  <AliasesSectionEditor
    bind:this={editorRef}
    initialData={{ aliases: initialData.aliases }}
    slug={publicId}
    save={saveLocationClaims}
    {onsaved}
    {onerror}
  />
{/if}
