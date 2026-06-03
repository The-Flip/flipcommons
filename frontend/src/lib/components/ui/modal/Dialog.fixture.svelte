<script lang="ts">
  import Dialog from './Dialog.svelte';

  let {
    useInitialFocus = false,
    useStaleInitialFocus = false,
    useAriaLabelledBy = false,
  }: {
    useInitialFocus?: boolean;
    useStaleInitialFocus?: boolean;
    useAriaLabelledBy?: boolean;
  } = $props();

  let open = $state(false);
  let closeCount = $state(0);

  let firstBtnEl: HTMLButtonElement | undefined = $state();
  let secondBtnEl: HTMLButtonElement | undefined = $state();

  // A detached element to simulate a stale ref
  let detachedEl: HTMLElement | undefined = $state();
  if (typeof document !== 'undefined') {
    detachedEl = document.createElement('button');
  }

  function openDialog() {
    open = true;
  }

  function closeDialog() {
    closeCount++;
    open = false;
  }

  let initialFocusEl = $derived(
    useStaleInitialFocus ? detachedEl : useInitialFocus ? secondBtnEl : undefined,
  );
</script>

<button type="button" onclick={openDialog}>Open dialog</button>

{#if useAriaLabelledBy}
  <Dialog {open} onclose={closeDialog} ariaLabelledBy="dialog-title" initialFocus={initialFocusEl}>
    <div class="panel">
      <h2 id="dialog-title">Dialog Title</h2>
      <button type="button" bind:this={firstBtnEl}>First</button>
      <button type="button" bind:this={secondBtnEl}>Second</button>
    </div>
  </Dialog>
{:else}
  <Dialog {open} onclose={closeDialog} ariaLabel="Test Dialog" initialFocus={initialFocusEl}>
    <div class="panel">
      <button type="button" bind:this={firstBtnEl}>First</button>
      <button type="button" bind:this={secondBtnEl}>Second</button>
    </div>
  </Dialog>
{/if}

<p data-testid="close-count">{closeCount}</p>

<style>
  .panel {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: var(--color-bg);
    padding: var(--size-3);
  }
</style>
