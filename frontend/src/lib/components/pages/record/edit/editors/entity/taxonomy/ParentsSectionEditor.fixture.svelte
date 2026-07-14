<script lang="ts">
  import ParentsSectionEditor from './ParentsSectionEditor.svelte';
  import type {
    SaveMeta,
    SaveResult,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';

  let {
    initialData = { parents: [{ public_id: 'physical-feature', name: 'Physical Feature' }] },
    slug = 'pop-bumper',
    saveResult = { ok: true } as SaveResult,
    type = 'gameplay-feature',
  }: {
    initialData?: { parents: { public_id: string; name?: string }[] };
    slug?: string;
    saveResult?: SaveResult;
    type?: string;
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

  async function save(_slug: string, body: { parents: string[] } & SaveMeta): Promise<SaveResult> {
    lastSaveBody = body;
    return saveResult;
  }
</script>

<ParentsSectionEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  {save}
  {type}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
<p data-testid="last-save-body">{JSON.stringify(lastSaveBody)}</p>
