<!--
@component
Test fixture for RelatedModelsEditor: mounts the editor with dirty/save probes
so the dom test can drive the section-editor contract without the modal shell.
-->
<script lang="ts">
  import type { ModelExportMarketSchema, ModelRelationshipSchema } from '$lib/api/schema';
  import RelatedModelsEditor from './RelatedModelsEditor.svelte';

  type RelatedModels = {
    variant_of?: { public_id: string; name?: string } | null;
    remake_of?: { public_id: string; name?: string } | null;
    export_edition_of?: { public_id: string; name?: string } | null;
    relationships?: ModelRelationshipSchema[];
    export_markets?: ModelExportMarketSchema[];
  };

  let {
    initialData,
    slug = 'medieval-madness',
  }: {
    initialData: RelatedModels;
    slug?: string;
  } = $props();

  let savedCount = $state(0);
  let lastError = $state('');

  let editorRef:
    | {
        save(meta?: unknown): Promise<void>;
        readonly dirty: boolean;
      }
    | undefined = $state();

  let editorDirty = $derived(editorRef?.dirty ?? false);
</script>

<RelatedModelsEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
