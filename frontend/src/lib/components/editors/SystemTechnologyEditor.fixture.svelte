<script lang="ts">
  import SystemTechnologyEditor from './SystemTechnologyEditor.svelte';
  import { saveSystemClaims } from '../../../routes/systems/[slug]/edit/save-system-claims';

  type InitialData = {
    technology_subgeneration?: { public_id: string } | null;
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

<SystemTechnologyEditor
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
