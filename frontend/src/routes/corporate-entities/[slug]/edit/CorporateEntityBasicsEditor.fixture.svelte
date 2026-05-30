<script lang="ts">
  import CorporateEntityBasicsEditor from './CorporateEntityBasicsEditor.svelte';
  import type { CorporateEntityEditView } from './corporate-entity-edit-types';

  let {
    initialData = {
      name: 'Williams Electronics',
      slug: 'williams-electronics',
      description: { text: '', plain: '', html: '', citations: [], attribution: null },
      year_start: 1985,
      year_end: 1999,
      aliases: [],
    },
    slug = 'williams-electronics',
  }: {
    initialData?: CorporateEntityEditView;
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
</script>

<CorporateEntityBasicsEditor
  bind:this={editorRef}
  {initialData}
  {slug}
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
