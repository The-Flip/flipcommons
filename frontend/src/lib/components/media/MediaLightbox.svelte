<script lang="ts">
  import { resolve } from '$app/paths';
  import type { UploadedMediaSchema } from '$lib/api/schema';
  import Dialog from '$lib/components/ui/modal/Dialog.svelte';

  type UploadedMedia = UploadedMediaSchema;

  let {
    media,
    initialIndex,
    onclose,
  }: {
    media: UploadedMedia[];
    initialIndex: number;
    onclose: () => void;
  } = $props();

  // Mutable — mutated locally by prev/next. Lightbox remounts each time,
  // so capturing the initial value once is intentional.
  // svelte-ignore state_referenced_locally
  let index = $state(initialIndex);

  let item = $derived(media[index]);

  let closeBtnEl: HTMLButtonElement | undefined = $state();

  function prev() {
    if (index > 0) index--;
  }

  function next() {
    if (index < media.length - 1) index++;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowLeft') prev();
    else if (e.key === 'ArrowRight') next();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<Dialog open={true} {onclose} ariaLabel="Media viewer" scrim="strong" initialFocus={closeBtnEl}>
  <button class="close-btn" onclick={onclose} aria-label="Close" bind:this={closeBtnEl}
    >&times;</button
  >

  <div class="lightbox-content">
    {#if item}
      <img src={item.renditions.display} alt="" class="display-img" />

      {#if index > 0}
        <button class="nav-btn nav-btn--prev" onclick={prev} aria-label="Previous">&#8249;</button>
      {/if}
      {#if index < media.length - 1}
        <button class="nav-btn nav-btn--next" onclick={next} aria-label="Next">&#8250;</button>
      {/if}

      <div class="lightbox-footer">
        {#if item.category}
          <span class="category">{item.category}</span>
        {/if}
        {#if item.uploaded_by_username}
          <span class="uploader">
            Uploaded by <a
              href={resolve(`/users/${item.uploaded_by_username}`)}
              class="uploader-link">{item.uploaded_by_username}</a
            >
          </span>
        {/if}
        <span class="counter">{index + 1} / {media.length}</span>
      </div>
    {/if}
  </div>
</Dialog>

<style>
  .lightbox-content {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--size-2);
  }

  .display-img {
    max-width: 90vw;
    max-height: 80vh;
    object-fit: contain;
    border-radius: var(--radius-2);
  }

  .close-btn {
    position: absolute;
    top: var(--size-3);
    right: var(--size-3);
    background: none;
    border: none;
    color: var(--color-text-inverse);
    font-size: 2rem;
    cursor: pointer;
    padding: var(--size-1);
    line-height: 1;
    opacity: 0.8;
  }

  .close-btn:hover {
    opacity: 1;
  }

  .nav-btn {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: var(--color-scrim);
    border: none;
    color: var(--color-text-inverse);
    font-size: 2.5rem;
    padding: var(--size-2) var(--size-3);
    cursor: pointer;
    border-radius: var(--radius-2);
    line-height: 1;
    opacity: 0.7;
    transition: opacity 0.15s ease;
  }

  .nav-btn:hover {
    opacity: 1;
  }

  .nav-btn--prev {
    left: -4rem;
  }

  .nav-btn--next {
    right: -4rem;
  }

  .lightbox-footer {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: var(--size-3);
    color: var(--color-text-inverse-muted);
    font-size: var(--font-size-1);
  }

  .uploader-link {
    color: var(--color-link);
  }

  @media (--breakpoint-narrow) {
    .nav-btn--prev {
      left: 0.5rem;
    }

    .nav-btn--next {
      right: 0.5rem;
    }
  }
</style>
