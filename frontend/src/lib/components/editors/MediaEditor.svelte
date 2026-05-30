<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import { detachMedia, setCategory, setPrimary } from '$lib/api/media-api';
  import { ENTITY_META, type MediaSupportedEntityKey } from '$lib/entities/entity-meta';
  import type { UploadedMediaSchema } from '$lib/api/schema';
  import Button from '$lib/components/Button.svelte';
  import MediaUploadZone from '$lib/components/media/MediaUploadZone.svelte';
  import MediaGrid from '$lib/components/media/MediaGrid.svelte';
  import { toast } from '$lib/toast/toast.svelte';

  type UploadedMedia = UploadedMediaSchema;
  type MediaEntityKey = MediaSupportedEntityKey;

  let {
    entityType,
    slug,
    media,
  }: {
    entityType: MediaEntityKey;
    slug: string;
    media: UploadedMedia[];
  } = $props();

  const categories = $derived(ENTITY_META[entityType].media_categories);

  let actionError = $state('');
  let mode = $state<'list' | 'upload'>('list');
  let isUploading = $state(false);
  let highlightUuids = $state<string[]>([]);
  // Seeds MediaGrid's initial filter on the post-upload remount.
  // Cleared on every entry into upload mode so a cancel doesn't stick a stale filter.
  let initialCategory = $state<string | null>(null);

  async function handleUploaded(uuids: string[], category: string) {
    actionError = '';
    mode = 'list';
    initialCategory = category;
    // Await invalidate first so the highlight effect sees the new media
    // when the signal lands. Reversed order would scroll against stale data.
    await invalidateAll();
    highlightUuids = uuids;
  }

  function enterUploadMode() {
    actionError = '';
    initialCategory = null;
    mode = 'upload';
  }

  function cancelUpload() {
    if (isUploading) return;
    mode = 'list';
  }

  async function refreshAfterWrite() {
    try {
      await invalidateAll();
    } catch {
      // Best-effort refresh; the write already succeeded and the next
      // navigation will pick up the new state.
    }
  }

  async function handleDelete(assetUuid: string) {
    actionError = '';
    try {
      await detachMedia(entityType, slug, assetUuid);
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'Failed to remove image.';
      return;
    }
    toast.success('Image removed.');
    await refreshAfterWrite();
  }

  async function handleSetPrimary(assetUuid: string) {
    actionError = '';
    try {
      await setPrimary(entityType, slug, assetUuid);
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'Failed to set primary image.';
      return;
    }
    toast.success('Set as primary image.');
    await refreshAfterWrite();
  }

  async function handleCategoryChange(assetUuid: string, category: string) {
    actionError = '';
    const previous = media.find((m) => m.asset_uuid === assetUuid)?.category ?? 'none';
    try {
      await setCategory(entityType, slug, assetUuid, category);
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'Failed to change image category.';
      return;
    }
    toast.success(`Image category changed from ${previous} to ${category}.`);
    await refreshAfterWrite();
  }
</script>

<div class="media-editor">
  {#if actionError}
    <p class="action-error">{actionError}</p>
  {/if}

  <div class="toolbar">
    {#if mode === 'list'}
      <Button onclick={enterUploadMode}>Upload images</Button>
    {:else}
      <Button onclick={cancelUpload} disabled={isUploading}>Cancel</Button>
    {/if}
  </div>

  {#if mode === 'upload'}
    <MediaUploadZone
      {entityType}
      {slug}
      onuploaded={handleUploaded}
      onuploadingchange={(u) => (isUploading = u)}
    />
  {:else}
    <MediaGrid
      {media}
      categories={[...categories]}
      canEdit={true}
      {highlightUuids}
      {initialCategory}
      ondelete={handleDelete}
      onsetprimary={handleSetPrimary}
      oncategorychange={handleCategoryChange}
    />
  {/if}
</div>

<style>
  .media-editor {
    display: flex;
    flex-direction: column;
    gap: var(--size-4);
  }

  .toolbar {
    display: flex;
  }

  .action-error {
    color: var(--color-error-text);
    font-size: var(--font-size-1);
    margin: 0;
  }
</style>
