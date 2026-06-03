<script lang="ts">
  import NameEditor from './NameEditor.svelte';
  import type { SaveMeta, SaveResult } from './save-claims-shared';

  let {
    initialData = { name: 'Williams', slug: 'williams' },
    initialAbbreviations,
    slug = 'williams',
    saveResult = { ok: true } as SaveResult,
  }: {
    initialData?: { name: string; slug: string };
    initialAbbreviations?: string[];
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
    body: {
      fields?: Partial<{ name: string; slug: string }>;
      abbreviations?: string[];
    } & SaveMeta,
  ): Promise<SaveResult> {
    lastSaveBody = body;
    return saveResult;
  }
</script>

<NameEditor
  bind:this={editorRef}
  {initialData}
  {initialAbbreviations}
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
