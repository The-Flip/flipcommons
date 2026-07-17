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

<SystemManufacturerEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  save={saveSystemClaims}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
