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

  let savedCount = $state(0);
  let lastError = $state('');
  let lastSaveBody = $state<unknown>(null);

  let editorRef:
    | {
        save(meta?: SaveMeta): Promise<void>;
        readonly dirty: boolean;
      }
    | undefined = $state();

  let editorDirty = $derived(editorRef?.dirty ?? false);

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
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
<p data-testid="last-save-body">{JSON.stringify(lastSaveBody)}</p>
