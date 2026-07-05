<script lang="ts">
  import type { CitationInstanceDraft } from './citation-types';
  import { citationTypeFrontend, citationTypeMeta } from '$lib/citation-types';
  import DropdownButton from '$lib/components/input/dropdown/DropdownButton.svelte';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';

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

  // The source's citation type drives the prompt and the inline validation —
  // a video child asks for a start time; books and pages stay freeform.
  let meta = $derived(citationTypeMeta(draft.sourceType));
  let frontend = $derived(citationTypeFrontend(draft.sourceType));

  // A pasted URL's start time (?t=95) arrives as a prefill, not as a
  // submitted locator — the contributor still confirms or edits it here.
  let locator = $state('');
  $effect.pre(() => {
    if (draft.locatorHint && !locator) locator = draft.locatorHint;
  });
  let validationError = $state('');
  let inputEl: HTMLInputElement | undefined = $state();

  $effect(() => {
    if (inputEl) {
      inputEl.focus();
    }
  });

  /** Validate against the type's grammar (UX mirror; the backend re-validates)
   *  and submit the canonical form. An empty locator is always a valid skip. */
  function trySubmit() {
    const trimmed = locator.trim();
    if (!trimmed) {
      onsubmit('');
      return;
    }
    const normalized = frontend.normalizeLocator(trimmed);
    if (normalized === null) {
      validationError = meta.locatorInvalidMessage;
      return;
    }
    onsubmit(normalized);
  }

  function handleKeydown(e: KeyboardEvent) {
    switch (e.key) {
      case 'Enter':
        e.preventDefault();
        trySubmit();
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
  <FieldGroup label={meta.locatorLabel} hint={meta.locatorHelp} optional error={validationError}>
    {#snippet children(inputId, describedBy)}
      <input
        bind:this={inputEl}
        id={inputId}
        type="text"
        aria-invalid={validationError ? 'true' : undefined}
        aria-describedby={describedBy}
        placeholder={meta.locatorPlaceholder}
        bind:value={locator}
        oninput={() => (validationError = '')}
        onkeydown={handleKeydown}
      />
    {/snippet}
  </FieldGroup>
  <div class="locator-actions">
    <DropdownButton
      onpointerdown={(e) => {
        e.preventDefault();
        trySubmit();
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
