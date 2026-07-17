<script lang="ts">
  import TitleFranchiseEditor from './TitleFranchiseEditor.svelte';

  type FranchiseTitle = {
    franchise?: { public_id: string; name: string } | null;
    series?: { public_id: string; name: string } | null;
  };

  let {
    initialData,
    slug = 'addams-family',
  }: {
    initialData: FranchiseTitle;
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

<TitleFranchiseEditor
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
