<script lang="ts">
  import AliasesSectionEditor from './AliasesSectionEditor.svelte';
  import type { SaveMeta, SaveResult } from './save-claims-shared';

  let {
    initialData = { aliases: ['Slingshot'] },
    slug = 'pop-bumper',
    saveResult = { ok: true } as SaveResult,
  }: {
    initialData?: { aliases: string[] };
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

  async function save(_slug: string, body: { aliases: string[] } & SaveMeta): Promise<SaveResult> {
    lastSaveBody = body;
    return saveResult;
  }
</script>

<AliasesSectionEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  {save}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>
<button type="button" onclick={() => editorRef?.save({ note: 'rationale' })}>Save with note</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
<p data-testid="last-save-body">{JSON.stringify(lastSaveBody)}</p>
