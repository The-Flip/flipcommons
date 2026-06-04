<script lang="ts">
  import SystemManufacturerEditor from './SystemManufacturerEditor.svelte';
  import { saveSystemClaims } from './save-system-claims';

  type InitialData = {
    manufacturer?: { public_id: string; name: string } | null;
  };

  let {
    initialData,
    slug = 'wpc-95',
  }: {
    initialData: InitialData;
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

<SystemManufacturerEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  save={saveSystemClaims}
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
