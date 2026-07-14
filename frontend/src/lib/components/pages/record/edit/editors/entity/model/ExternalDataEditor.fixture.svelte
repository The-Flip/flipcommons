<script lang="ts">
  import ExternalDataEditor from './ExternalDataEditor.svelte';

  type ExternalDataModel = {
    ipdb_id?: number | null;
    opdb_id?: string | null;
    pinside_id?: string | null;
  };

  let {
    initialData,
    slug = 'medieval-madness',
  }: {
    initialData: ExternalDataModel;
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

<ExternalDataEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
