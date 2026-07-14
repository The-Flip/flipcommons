<!--
@component
Test fixture for RelatedModelsEditor: mounts the editor with dirty/save probes
so the dom test can drive the section-editor contract without the modal shell.
-->
<script lang="ts">
  import type { ModelRelationshipSchema } from '$lib/api/schema';
  import RelatedModelsEditor from './RelatedModelsEditor.svelte';

  type RelatedModels = {
    variant_of?: { public_id: string; name?: string } | null;
    remake_of?: { public_id: string; name?: string } | null;
    relationships?: ModelRelationshipSchema[];
  };

  let {
    initialData,
    slug = 'medieval-madness',
  }: {
    initialData: RelatedModels;
    slug?: string;
  } = $props();

  let dirtyFromCallback = $state(false);
  let dirtyFromHandle = $state('unknown');
  let savedCount = $state(0);
  let lastError = $state('');

  let editorRef:
    | {
        save(meta?: unknown): Promise<void>;
        isDirty(): boolean;
      }
    | undefined = $state();
</script>

<RelatedModelsEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
  ondirtychange={(dirty) => (dirtyFromCallback = dirty)}
/>

<button type="button" onclick={() => (dirtyFromHandle = String(editorRef?.isDirty() ?? false))}>
  Check dirty
</button>
<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty-callback">{String(dirtyFromCallback)}</p>
<p data-testid="dirty-handle">{dirtyFromHandle}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
