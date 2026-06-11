<script lang="ts">
  import client from '$lib/api/client';
  import type { ParentContext, ExtractionDraft } from './citation-types';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';

  type SourceType = 'book' | 'magazine' | 'web';

  let {
    parentContext,
    prefillName,
    extractionDraft = null,
    onsourcecreated,
    oncancel,
    onback,
  }: {
    parentContext: ParentContext | null;
    prefillName: string;
    extractionDraft?: ExtractionDraft | null;
    onsourcecreated: (result: {
      sourceId: number;
      sourceName: string;
      skipLocator: boolean;
    }) => void;
    oncancel: () => void;
    onback: () => void;
  } = $props();

  // These props are intentionally captured once at mount — the orchestrator
  // creates a fresh component for each stage transition, so they won't change.
  // svelte-ignore state_referenced_locally
  let name = $state(prefillName);
  // svelte-ignore state_referenced_locally
  let sourceType = $state<SourceType>(
    extractionDraft
      ? (extractionDraft.source_type as SourceType)
      : parentContext
        ? (parentContext.source_type as SourceType)
        : 'book',
  );
  // svelte-ignore state_referenced_locally
  let author = $state(extractionDraft?.author ?? parentContext?.author ?? '');
  // svelte-ignore state_referenced_locally
  let publisher = $state(extractionDraft?.publisher ?? '');
  // svelte-ignore state_referenced_locally
  let year = $state<number | null>(extractionDraft?.year ?? null);
  // svelte-ignore state_referenced_locally
  let url = $state(extractionDraft?.url ?? '');
  let error = $state('');
  let submitting = $state(false);
  let nameInputEl: HTMLInputElement | undefined = $state();

  let showTypePicker = $derived(!parentContext && !extractionDraft);
  let showUrlField = $derived(sourceType === 'web');
  let showAuthorField = $derived(sourceType === 'book' || sourceType === 'magazine');
  let showPublisherField = $derived(!!extractionDraft);
  let showYearField = $derived(!!extractionDraft);

  $effect(() => {
    if (nameInputEl) {
      nameInputEl.focus();
    }
  });

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      oncancel();
    }
  }

  async function submit() {
    if (!name.trim()) {
      error = 'Name is required.';
      return;
    }
    if (sourceType === 'web' && !url.trim()) {
      error = 'URL is required for web sources.';
      return;
    }

    submitting = true;
    error = '';

    const { data, error: apiError } = await client.POST('/api/citation-sources/', {
      body: {
        name,
        source_type: sourceType,
        author: showAuthorField ? author : '',
        publisher: showPublisherField ? publisher : '',
        year: year ?? null,
        date_note: '',
        isbn: extractionDraft?.isbn ?? null,
        description: '',
        parent_id: parentContext?.id ?? null,
        identifier: '',
        url: showUrlField && url.trim() ? url : null,
        link_label: '',
        // A child is a specific page (reference); only a root holds its own
        // homepage. 'homepage' on a child page would let it pose as a domain
        // root in later URL recognition.
        link_type: parentContext ? 'reference' : 'homepage',
      },
    });
    submitting = false;

    if (apiError) {
      error = typeof apiError === 'string' ? apiError : 'Failed to create source.';
      return;
    }

    onsourcecreated({
      sourceId: data.id,
      sourceName: data.name,
      skipLocator: data.skip_locator,
    });
  }
</script>

<DropdownHeader {onback}>New source</DropdownHeader>
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<form
  class="create-form"
  onsubmit={(e) => {
    e.preventDefault();
    submit();
  }}
  onkeydown={handleKeydown}
>
  {#if showTypePicker}
    <div class="type-chips">
      {#each ['book', 'magazine', 'web'] as t (t)}
        <button
          type="button"
          class="type-chip"
          class:selected={sourceType === t}
          onpointerdown={(e) => {
            e.preventDefault();
            sourceType = t as SourceType;
          }}
        >
          {t}
        </button>
      {/each}
    </div>
  {/if}
  {#if extractionDraft && sourceType === 'web'}
    <div class="extraction-note">Scraped from page — review before saving</div>
  {/if}
  <input
    bind:this={nameInputEl}
    type="text"
    placeholder="Name"
    bind:value={name}
    autocomplete="off"
    data-1p-ignore
    data-lpignore="true"
  />
  {#if showAuthorField}
    <input
      type="text"
      placeholder="Author (optional)"
      bind:value={author}
      autocomplete="off"
      data-1p-ignore
      data-lpignore="true"
    />
  {/if}
  {#if showPublisherField}
    <input
      type="text"
      placeholder="Publisher (optional)"
      bind:value={publisher}
      autocomplete="off"
      data-1p-ignore
      data-lpignore="true"
    />
  {/if}
  {#if showYearField}
    <input
      type="text"
      inputmode="numeric"
      placeholder="Year (optional)"
      value={year ?? ''}
      oninput={(e) => {
        const v = (e.currentTarget as HTMLInputElement).value.trim();
        const n = v ? parseInt(v, 10) : null;
        year = n !== null && !isNaN(n) ? n : null;
      }}
      autocomplete="off"
      data-1p-ignore
      data-lpignore="true"
    />
  {/if}
  {#if showUrlField}
    <input
      type="url"
      placeholder="URL"
      bind:value={url}
      autocomplete="off"
      data-1p-ignore
      data-lpignore="true"
    />
  {/if}
  {#if error}
    <div class="form-error">{error}</div>
  {/if}
  <button type="submit" class="submit-btn" disabled={submitting}>
    {submitting ? 'Creating\u2026' : 'Create & cite'}
  </button>
</form>

<style>
  .create-form {
    padding: var(--size-2) var(--size-3);
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .type-chips {
    display: flex;
    gap: var(--size-1);
  }

  .type-chip {
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    font-family: inherit;
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
    background-color: var(--color-input-bg);
    color: var(--color-text);
    cursor: pointer;
    text-transform: capitalize;
  }

  .type-chip.selected {
    background-color: var(--color-input-focus-ring);
    border-color: var(--color-input-focus);
  }

  .extraction-note {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    font-style: italic;
  }

  .form-error {
    color: var(--color-error-text);
    font-size: var(--font-size-0);
  }

  .submit-btn {
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-1);
    font-family: inherit;
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
    background-color: var(--color-input-focus-ring);
    color: var(--color-text);
    cursor: pointer;
  }

  .submit-btn:hover:not(:disabled) {
    border-color: var(--color-input-focus);
  }

  .submit-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
