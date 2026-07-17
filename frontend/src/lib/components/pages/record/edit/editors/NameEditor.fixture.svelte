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
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
<p data-testid="last-save-body">{JSON.stringify(lastSaveBody)}</p>
