<script lang="ts">
  import DescriptionEditor from './DescriptionEditor.svelte';
  import type { SaveResult } from './save-claims-shared';

  let savedCount = $state(0);
  let lastError = $state('');
  let lastSaveBody = $state<unknown>(null);

  let editorRef:
    | {
        save(meta?: unknown): Promise<void>;
        readonly dirty: boolean;
      }
    | undefined = $state();

  let editorDirty = $derived(editorRef?.dirty ?? false);

  async function save(_slug: string, body: unknown): Promise<SaveResult> {
    lastSaveBody = body;
    return { ok: true };
  }
</script>

<DescriptionEditor
  bind:this={editorRef}
  initialData="Original description"
  slug="medieval-madness"
  {save}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
<p data-testid="last-save-body">{JSON.stringify(lastSaveBody)}</p>
