<script lang="ts">
  import ParentsSectionEditor from './ParentsSectionEditor.svelte';
  import type { SaveMeta, SaveResult } from './save-claims-shared';

  let {
    initialData = { parents: [{ public_id: 'physical-feature', name: 'Physical Feature' }] },
    slug = 'pop-bumper',
    saveResult = { ok: true } as SaveResult,
    options = [
      { slug: 'pop-bumper', label: 'Pop Bumper', count: 50 },
      { slug: 'physical-feature', label: 'Physical Feature', count: 100 },
      { slug: 'spinner', label: 'Spinner', count: 25 },
    ],
  }: {
    initialData?: { parents: { public_id: string; name?: string }[] };
    slug?: string;
    saveResult?: SaveResult;
    options?: { slug: string; label: string; count?: number }[];
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

  async function save(_slug: string, body: { parents: string[] } & SaveMeta): Promise<SaveResult> {
    lastSaveBody = body;
    return saveResult;
  }

  async function optionsLoader() {
    return options;
  }
</script>

<ParentsSectionEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  {save}
  {optionsLoader}
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
