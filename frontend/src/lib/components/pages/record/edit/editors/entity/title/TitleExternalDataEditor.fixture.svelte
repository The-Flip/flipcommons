<script lang="ts">
  import TitleExternalDataEditor from './TitleExternalDataEditor.svelte';

  type ExternalDataTitle = {
    opdb_id?: string | null;
    fandom_page_id?: number | null;
  };

  let {
    initialData,
    slug = 'addams-family',
  }: {
    initialData: ExternalDataTitle;
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

<TitleExternalDataEditor
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
