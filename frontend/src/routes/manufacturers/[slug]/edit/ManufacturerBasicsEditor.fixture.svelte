<script lang="ts">
  import ManufacturerBasicsEditor from './ManufacturerBasicsEditor.svelte';
  import type { ManufacturerEditView } from './manufacturer-edit-types';

  let {
    initialData = {
      name: 'Williams',
      slug: 'williams',
      website: 'https://williams.example',
      logo_url: 'https://williams.example/logo.png',
      description: {
        text: 'Historic manufacturer',
        plain: 'Historic manufacturer',
        html: '',
        citations: [],
      },
    },
    slug = 'williams',
  }: {
    initialData?: ManufacturerEditView;
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

<ManufacturerBasicsEditor
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
