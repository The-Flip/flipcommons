<script lang="ts">
  import TechnologyEditor from './TechnologyEditor.svelte';

  type TechnologyModel = {
    technology_generation?: { public_id: string } | null;
    technology_subgeneration?: { public_id: string } | null;
    system?: { public_id: string } | null;
    display_type?: { public_id: string } | null;
    display_subtype?: { public_id: string } | null;
  };

  let {
    initialData,
    slug = 'medieval-madness',
  }: {
    initialData: TechnologyModel;
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

  function handleSaved() {
    savedCount++;
  }

  function handleError(msg: string) {
    lastError = msg;
  }
</script>

<TechnologyEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  onsaved={handleSaved}
  onerror={handleError}
  ondirtychange={(dirty) => (dirtyFromCallback = dirty)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>
<button type="button" onclick={() => (dirtyFromHandle = String(editorRef?.isDirty() ?? false))}>
  Check dirty
</button>
<button
  type="button"
  onclick={() =>
    editorRef?.save({
      note: 'Corrected per flyer',
      citations: [{ citation_source_id: 7, locator: 'p. 2' }],
    })}
>
  Save with meta
</button>

<p data-testid="dirty-callback">{String(dirtyFromCallback)}</p>
<p data-testid="dirty-handle">{dirtyFromHandle}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
