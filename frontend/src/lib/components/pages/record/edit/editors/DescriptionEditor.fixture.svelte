<script lang="ts">
  import DescriptionEditor from './DescriptionEditor.svelte';
  import type { SaveResult } from './save-claims-shared';

  let dirtyFromCallback = $state(false);
  let dirtyFromHandle = $state('unknown');
  let savedCount = $state(0);
  let lastError = $state('');
  let lastSaveBody = $state<unknown>(null);

  let editorRef:
    | {
        save(): Promise<void>;
        isDirty(): boolean;
      }
    | undefined = $state();

  function handleDirtyChange(dirty: boolean) {
    dirtyFromCallback = dirty;
  }

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
  ondirtychange={handleDirtyChange}
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
