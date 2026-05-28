<script lang="ts">
  import { MEDIA_CATEGORIES } from '$lib/models/model-meta';
  import { IMAGE_ACCEPT } from '$lib/api/media-api';
  import { createUploadManager } from '$lib/media-upload.svelte';
  import Button from '$lib/components/Button.svelte';

  type MediaEntityKey = keyof typeof MEDIA_CATEGORIES;

  let {
    entityType,
    slug,
    onuploaded,
    onuploadingchange,
  }: {
    entityType: MediaEntityKey;
    slug: string;
    onuploaded: (uuids: string[], category: string) => void;
    onuploadingchange?: (uploading: boolean) => void;
  } = $props();

  const categories = $derived(MEDIA_CATEGORIES[entityType]);

  let fileInput: HTMLInputElement | undefined = $state();
  let category = $state('');
  let isDragging = $state(false);

  const manager = createUploadManager();

  let lastUploading = false;
  $effect(() => {
    const u = manager.isUploading;
    if (u === lastUploading) return;
    lastUploading = u;
    onuploadingchange?.(u);
  });

  const canUpload = $derived(category !== '' && !manager.isUploading);

  function openPicker() {
    fileInput?.click();
  }

  async function handleFiles() {
    const files = fileInput?.files;
    if (!files || files.length === 0) return;
    await processFiles(files);
    if (fileInput) fileInput.value = '';
  }

  async function processFiles(files: FileList) {
    await manager.upload(files, entityType, slug, { category });

    const hadError = manager.files.some((f) => f.status === 'error');

    if (!hadError) {
      const uuids = manager.files
        .filter((f) => f.status === 'success' && f.result)
        .map((f) => f.result!.asset_uuid);
      const uploadedCategory = category;
      manager.reset();
      onuploaded(uuids, uploadedCategory);
    }
  }

  function handleDragEnter(e: DragEvent) {
    e.preventDefault();
    if (!canUpload) return;
    isDragging = true;
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
  }

  function handleDragLeave(e: DragEvent) {
    if (e.currentTarget === e.target || !e.relatedTarget) {
      isDragging = false;
    }
  }

  async function handleDrop(e: DragEvent) {
    e.preventDefault();
    isDragging = false;
    if (!canUpload) return;
    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;
    await processFiles(files);
  }
</script>

<div class="upload-page">
  <div class="options">
    <select bind:value={category} class="category-select">
      <option value="" disabled>Choose a category…</option>
      {#each categories as cat (cat)}
        <option value={cat}>{cat}</option>
      {/each}
    </select>
  </div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="drop-zone"
    class:dragging={isDragging}
    class:disabled={!canUpload}
    ondragenter={handleDragEnter}
    ondragover={handleDragOver}
    ondragleave={handleDragLeave}
    ondrop={handleDrop}
  >
    <div class="drop-zone-content">
      {#if category}
        <span class="drop-icon">&#8683;</span>
        <p class="drop-text">Drag and drop images here</p>
        <p class="drop-or">or</p>
        <Button onclick={openPicker} disabled={!canUpload}>Select Images</Button>
      {:else}
        <p class="drop-text">Choose category to upload images</p>
      {/if}
    </div>
  </div>

  <input
    bind:this={fileInput}
    type="file"
    accept={IMAGE_ACCEPT}
    multiple
    class="hidden-input"
    onchange={handleFiles}
  />

  {#if manager.files.length > 0}
    <div class="file-list-header">
      <span class="file-list-title">
        {#if manager.isUploading}
          Uploading...
        {:else}
          Upload results
        {/if}
      </span>
    </div>
    <ul class="file-list">
      {#each manager.files as entry, i (entry.file.name + entry.file.lastModified + i)}
        <li class="file-entry" class:error={entry.status === 'error'}>
          <span class="file-name">{entry.file.name}</span>
          <span class="file-status">
            {#if entry.status === 'uploading' && entry.progress >= 100}
              Processing...
            {:else if entry.status === 'uploading'}
              <span class="progress-bar">
                <span class="progress-fill" style:width="{entry.progress}%"></span>
              </span>
              {entry.progress}%
            {:else if entry.status === 'success'}
              Done
            {:else if entry.status === 'error'}
              {entry.error}
            {:else}
              Pending
            {/if}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .upload-page {
    max-width: 36rem;
  }

  .options {
    display: flex;
    align-items: center;
    gap: var(--size-4);
    flex-wrap: wrap;
    margin-bottom: var(--size-4);
  }

  .category-select {
    padding: var(--size-1) var(--size-2);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background: var(--color-surface);
    color: var(--color-text);
    font-size: var(--font-size-1);
  }

  .drop-zone {
    border: 2px dashed var(--color-border-soft);
    border-radius: var(--radius-3, 0.5rem);
    padding: var(--size-8, 3rem) var(--size-4);
    text-align: center;
    transition:
      border-color 0.15s ease,
      background-color 0.15s ease;
  }

  .drop-zone.dragging {
    border-color: var(--color-link);
    background: color-mix(in srgb, var(--color-accent) 5%, transparent);
  }

  .drop-zone.disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .drop-zone-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--size-1);
  }

  .drop-icon {
    font-size: 2.5rem;
    line-height: 1;
    color: var(--color-text-muted);
    opacity: 0.5;
  }

  .drop-text {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    margin: 0;
  }

  .drop-or {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0;
  }

  .hidden-input {
    display: none;
  }

  .file-list-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--size-4);
  }

  .file-list-title {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }

  .file-list {
    list-style: none;
    padding: 0;
    margin: var(--size-2) 0 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .file-entry {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--size-3);
    font-size: var(--font-size-0);
    padding: var(--size-1) var(--size-2);
    border-radius: var(--radius-1);
    background: var(--color-surface);
  }

  .file-entry.error {
    color: var(--color-error-text);
  }

  .file-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .file-status {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    white-space: nowrap;
    flex-shrink: 0;
  }

  .progress-bar {
    width: 6rem;
    height: 0.4rem;
    background: var(--color-border-soft);
    border-radius: 999px;
    overflow: hidden;
  }

  .progress-fill {
    display: block;
    height: 100%;
    background: var(--color-accent);
    transition: width 0.15s ease;
  }
</style>
