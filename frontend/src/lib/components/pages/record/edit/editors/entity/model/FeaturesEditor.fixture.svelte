<script lang="ts">
  import FeaturesEditor from './FeaturesEditor.svelte';

  type FeaturesModel = {
    cabinet?: { public_id: string } | null;
    reward_types: { public_id: string }[];
    tags: { public_id: string }[];
    themes: { public_id: string; name: string }[];
    production_quantity: string;
    player_count?: number | null;
    flipper_count?: number | null;
    gameplay_features: { public_id: string; name?: string; count?: number | null }[];
  };

  let {
    initialData,
    slug = 'medieval-madness',
  }: {
    initialData: FeaturesModel;
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

<FeaturesEditor
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
