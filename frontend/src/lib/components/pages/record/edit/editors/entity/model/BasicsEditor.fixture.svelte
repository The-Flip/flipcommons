<script lang="ts">
  import BasicsEditor from './BasicsEditor.svelte';

  type BasicsModel = {
    year?: number | null;
    month?: number | null;
    title?: { public_id: string; name: string } | null;
    corporate_entity?: { public_id: string; name: string } | null;
    game_format?: { public_id: string } | null;
    production_status?: { public_id: string } | null;
  };

  let {
    initialData,
    slug = 'medieval-madness',
    slim = false,
  }: {
    initialData: BasicsModel;
    slug?: string;
    slim?: boolean;
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

<BasicsEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  {slim}
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
