<script lang="ts">
  import type { CitationInstanceDraft } from './citation-types';
  import DropdownButton from '$lib/components/input/dropdown/DropdownButton.svelte';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';

  let {
    draft,
    onsubmit,
    oncancel,
    onback,
  }: {
    draft: CitationInstanceDraft;
    onsubmit: (locator: string) => void;
    oncancel: () => void;
    onback: () => void;
  } = $props();

  let locator = $state('');
  let inputEl: HTMLInputElement | undefined = $state();

  $effect(() => {
    if (inputEl) {
      inputEl.focus();
    }
  });

  function handleKeydown(e: KeyboardEvent) {
    switch (e.key) {
      case 'Enter':
        e.preventDefault();
        onsubmit(locator);
        break;
      case 'Escape':
        e.preventDefault();
        oncancel();
        break;
      case 'Backspace':
        if (!locator) {
          e.preventDefault();
          onback();
        }
        break;
      case 'ArrowLeft':
        if (inputEl?.selectionStart === 0) {
          e.preventDefault();
          onback();
        }
        break;
    }
  }
</script>

<DropdownHeader {onback}>Citing: {draft.sourceName}</DropdownHeader>
<div class="locator-form">
  <input
    bind:this={inputEl}
    type="text"
    aria-label="Citation locator"
    placeholder="p. 42, Chapter 3, timestamp..."
    bind:value={locator}
    onkeydown={handleKeydown}
  />
  <div class="locator-actions">
    <DropdownButton
      onpointerdown={(e) => {
        e.preventDefault();
        onsubmit(locator);
      }}
    >
      Insert
    </DropdownButton>
    <button
      class="skip-btn"
      onpointerdown={(e) => {
        e.preventDefault();
        onsubmit('');
      }}
    >
      Skip
    </button>
  </div>
</div>

<style>
  .locator-form {
    padding: var(--size-2) var(--size-3);
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .locator-actions {
    display: flex;
    gap: var(--size-2);
    align-items: center;
  }

  .skip-btn {
    background: none;
    border: none;
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    cursor: pointer;
    text-decoration: underline;
    padding: 0;
  }

  .skip-btn:hover {
    color: var(--color-text);
  }
</style>
