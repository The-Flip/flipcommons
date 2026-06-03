<script lang="ts">
  import type { UploadedMediaSchema } from '$lib/api/schema';
  import PillSelect from '$lib/components/ui/PillSelect.svelte';

  type UploadedMedia = UploadedMediaSchema;

  let {
    asset,
    canEdit = false,
    categories = [],
    ondelete,
    onsetprimary,
    oncategorychange,
    onclick,
  }: {
    asset: UploadedMedia;
    canEdit?: boolean;
    categories?: string[];
    ondelete?: (assetUuid: string) => void;
    onsetprimary?: (assetUuid: string) => void;
    oncategorychange?: (assetUuid: string, category: string) => void;
    onclick?: (assetUuid: string) => void;
  } = $props();

  const categoryOptions = $derived(categories.map((c) => ({ value: c, label: c })));
  const showPill = $derived(canEdit && categoryOptions.length > 0);

  function stopCardKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') e.stopPropagation();
  }

  function handleDelete(e: MouseEvent) {
    e.stopPropagation();
    if (confirm('Remove this image from this machine?')) {
      ondelete?.(asset.asset_uuid);
    }
  }

  function handleSetPrimary(e: MouseEvent) {
    e.stopPropagation();
    onsetprimary?.(asset.asset_uuid);
  }

  function handleClick() {
    onclick?.(asset.asset_uuid);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onclick?.(asset.asset_uuid);
    }
  }
</script>

<div
  class="media-card"
  role="button"
  tabindex="0"
  aria-label={asset.category ? `Open ${asset.category} image` : 'Open image'}
  onclick={handleClick}
  onkeydown={handleKeydown}
>
  <div class="thumb-wrapper">
    <img src={asset.renditions.thumb} alt="" class="thumb" loading="lazy" />
    {#if showPill}
      <!-- The wrapper exists to position the pill and to keep click/keydown
           events from bubbling to the card's lightbox handler. The interactive
           element is the <button> inside PillSelect, not this div. -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="category-pill" onclick={(e) => e.stopPropagation()} onkeydown={stopCardKeydown}>
        <PillSelect
          value={asset.category}
          options={categoryOptions}
          purpose="Image category"
          onchange={(c) => oncategorychange?.(asset.asset_uuid, c)}
        />
      </div>
    {:else if asset.category}
      <span class="badge">{asset.category}</span>
    {/if}
    {#if asset.is_primary}
      <span class="primary-badge" title="Primary image">&#9733;</span>
    {/if}
  </div>

  {#if canEdit}
    <div class="actions">
      {#if !asset.is_primary}
        <button class="action-btn" onclick={handleSetPrimary} title="Set as primary">
          &#9734; Make Primary
        </button>
      {/if}
      <button class="action-btn action-btn--danger" onclick={handleDelete} title="Remove">
        &times; Remove
      </button>
    </div>
  {/if}
</div>

<style>
  .media-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    overflow: hidden;
    cursor: pointer;
    transition:
      box-shadow 0.15s ease,
      transform 0.15s ease;
  }

  .media-card:hover {
    box-shadow: var(--shadow-popover);
    transform: translateY(-1px);
  }

  .media-card:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }

  .thumb-wrapper {
    position: relative;
  }

  .thumb {
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
    display: block;
  }

  .badge {
    position: absolute;
    bottom: var(--size-1);
    left: var(--size-1);
    /* Badge scrim is intentionally more opaque than --color-scrim (0.5):
       it sits over arbitrary photo content and needs to guarantee legibility
       of the small label, not just dim the layer below. */
    /* stylelint-disable-next-line function-disallowed-list */
    background: rgba(0, 0, 0, 0.65);
    color: var(--color-text-inverse);
    font-size: var(--font-size-0);
    padding: 0.1em 0.4em;
    border-radius: var(--radius-1);
  }

  .category-pill {
    position: absolute;
    bottom: var(--size-1);
    left: var(--size-1);
    z-index: 1;
  }

  .primary-badge {
    position: absolute;
    top: var(--size-1);
    right: var(--size-1);
    color: var(--color-featured);
    font-size: 1.25rem;
    line-height: 1;
    /* Drop-shadow color is a filter primitive, not a themed surface color —
       a literal black w/ alpha is the right tool here. */
    /* stylelint-disable-next-line function-disallowed-list */
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5));
  }

  .actions {
    display: flex;
    gap: var(--size-1);
    padding: var(--size-1);
  }

  .action-btn {
    flex: 1;
    background: none;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-1);
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    cursor: pointer;
    color: var(--color-text-muted);
    transition: color 0.15s ease;
  }

  .action-btn:hover {
    color: var(--color-text);
    border-color: var(--color-border);
  }

  .action-btn--danger:hover {
    color: var(--color-error-text);
    border-color: var(--color-error-text);
  }
</style>
