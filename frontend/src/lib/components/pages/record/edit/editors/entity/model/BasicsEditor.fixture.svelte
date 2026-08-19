<script lang="ts">
  import BasicsEditor from './BasicsEditor.svelte';

  type BasicsModel = {
    production_year?: number | null;
    production_month?: number | null;
    project_year?: number | null;
    project_month?: number | null;
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

<BasicsEditor
  bind:this={editorRef}
  {initialData}
  {slug}
  {slim}
  onsaved={() => savedCount++}
  onerror={(message) => (lastError = message)}
/>

<button type="button" onclick={() => editorRef?.save()}>Save</button>

<p data-testid="dirty">{String(editorDirty)}</p>
<p data-testid="saved-count">{savedCount}</p>
<p data-testid="last-error">{lastError}</p>
