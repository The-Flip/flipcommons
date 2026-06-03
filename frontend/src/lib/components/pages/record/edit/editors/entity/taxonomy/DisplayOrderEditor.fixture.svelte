<script lang="ts">
  import DisplayOrderEditor from './DisplayOrderEditor.svelte';
  import type {
    SaveMeta,
    SaveResult,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';

  let {
    initialData = 1 as number | null,
    slug = 'cabinet-style',
    saveResult = { ok: true } as SaveResult,
  }: {
    initialData?: number | null;
    slug?: string;
    saveResult?: SaveResult;
  } = $props();

  let dirtyFromCallback = $state(false);
  let dirtyFromHandle = $state('unknown');
  let savedCount = $state(0);
  let lastError = $state('');
  let lastSaveBody = $state<unknown>(null);

  let editorRef:
    | {
        save(meta?: SaveMeta): Promise<void>;
        isDirty(): boolean;
      }
    | undefined = $state();

  async function save(
    _slug: string,
    body: { fields: Partial<{ display_order: string | number }> } & SaveMeta,
  ): Promise<SaveResult> {
    lastSaveBody = body;
    return saveResult;
  }
</script>

<DisplayOrderEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  {save}
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
<p data-testid="last-save-body">{JSON.stringify(lastSaveBody)}</p>
