<script lang="ts">
  import type { Snippet } from 'svelte';
  import Dialog from './Dialog.svelte';

  let {
    title,
    titleContent,
    open,
    onclose,
    headerActions,
    footer,
    children,
  }: {
    title: string;
    titleContent?: Snippet;
    open: boolean;
    onclose: () => void;
    headerActions?: Snippet;
    footer?: Snippet;
    children: Snippet;
  } = $props();

  let closeButtonEl: HTMLButtonElement | undefined = $state();
  const uid = $props.id();
  const titleId = `${uid}-title`;
  const bodyId = `${uid}-body`;

  function close() {
    onclose();
  }
</script>

<Dialog
  {open}
  {onclose}
  ariaLabelledBy={titleId}
  ariaDescribedBy={bodyId}
  initialFocus={closeButtonEl}
>
  <div class="modal-dialog">
    <header class="modal-header">
      <div class="header-main">
        <h2 id={titleId}>
          {#if titleContent}
            {@render titleContent()}
          {:else}
            {title}
          {/if}
        </h2>
        {#if headerActions}
          <div class="header-actions">
            {@render headerActions()}
          </div>
        {/if}
      </div>
      <button
        type="button"
        class="close-btn"
        aria-label="Close"
        onclick={close}
        bind:this={closeButtonEl}>&times;</button
      >
    </header>

    <div class="modal-body" id={bodyId}>
      {@render children()}
    </div>

    {#if footer}
      <footer class="modal-footer">
        {@render footer()}
      </footer>
    {/if}
  </div>
</Dialog>

<style>
  .modal-dialog {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: min(48rem, calc(100vw - 2 * var(--size-4)));
    max-height: calc(100vh - 2 * var(--size-4));
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-3);
    display: flex;
    flex-direction: column;
    box-shadow: var(--shadow-modal);
    overflow: hidden;
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--size-3);
    padding: var(--size-3) var(--size-4);
    border-bottom: 1px solid var(--color-border-soft);
    flex-shrink: 0;
  }

  .header-main {
    display: flex;
    flex: 1;
    align-items: center;
    justify-content: space-between;
    gap: var(--size-3);
    min-width: 0;
  }

  .modal-header h2 {
    font-size: var(--font-size-3);
    font-weight: 600;
    margin: 0;
    color: var(--color-text);
    min-width: 0;
  }

  .header-actions {
    flex-shrink: 0;
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--color-text-muted);
    font-size: 1.5rem;
    cursor: pointer;
    padding: var(--size-1);
    line-height: 1;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .modal-body {
    flex: 1;
    overflow-y: auto;
    padding: var(--size-4);
  }

  .modal-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--size-2);
    padding: var(--size-3) var(--size-4);
    border-top: 1px solid var(--color-border-soft);
    flex-shrink: 0;
  }

  @media (--breakpoint-narrow) {
    .modal-dialog {
      top: 0;
      left: 0;
      transform: none;
      width: 100vw;
      height: 100vh;
      max-height: none;
      border-radius: 0;
      border: none;
    }
  }
</style>
