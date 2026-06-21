<script lang="ts">
  import client from '$lib/api/client';
  import type { ParentContext, CreateSeed } from './citation-types';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';
  import TextField from '$lib/components/input/TextField.svelte';

  type SourceType = 'book' | 'magazine' | 'web';

  let {
    parentContext,
    seed,
    onsourcecreated,
    oncancel,
    onback,
  }: {
    parentContext: ParentContext | null;
    seed: CreateSeed;
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
  // Only an 'extraction' seed carries scraped metadata; 'name'/'web-url' don't.
  // svelte-ignore state_referenced_locally
  const draft = seed.kind === 'extraction' ? seed.draft : null;

  // svelte-ignore state_referenced_locally
  let name = $state(seed.kind === 'name' ? seed.name : (draft?.name ?? ''));
  // svelte-ignore state_referenced_locally
  let sourceType = $state<SourceType>(
    draft
      ? (draft.source_type as SourceType)
      : seed.kind === 'web-url'
        ? 'web'
        : parentContext
          ? (parentContext.source_type as SourceType)
          : 'book',
  );
  // svelte-ignore state_referenced_locally
  let author = $state(draft?.author ?? parentContext?.author ?? '');
  let publisher = $state(draft?.publisher ?? '');
  let year = $state<number | null>(draft?.year ?? null);
  // svelte-ignore state_referenced_locally
  let url = $state(draft?.url ?? (seed.kind === 'web-url' ? seed.url : ''));
  let error = $state('');
  let submitting = $state(false);
  let nameInputEl: HTMLInputElement | undefined = $state();

  // The picker shows only for a manual 'name' seed with no parent; a parent,
  // a scrape, or a pasted URL all lock the type.
  let showTypePicker = $derived(seed.kind === 'name' && !parentContext);
  let showUrlField = $derived(sourceType === 'web');
  let showAuthorField = $derived(sourceType === 'book' || sourceType === 'magazine');
  // Publisher and Year are book/magazine concerns; a web source is a site/page,
  // not a dated publication, so they're hidden for web. (PR 2's web rework
  // reintroduces a publisher-as-Site-name field on the web path.)
  let showPublisherField = $derived(seed.kind === 'extraction' && sourceType !== 'web');
  let showYearField = $derived(seed.kind === 'extraction' && sourceType !== 'web');

  // A web child (under a parent) skips the locator and cites on submit; every
  // other source advances to the locator step next. Mirrors
  // CitationSource.skip_locator so the button promises the right outcome.
  let citesImmediately = $derived(sourceType === 'web' && !!parentContext);
  let submitLabel = $derived(citesImmediately ? 'Create Citation' : 'Continue');

  // Show the "retrieved" note only when the scrape actually returned a title to
  // review; an extraction that found nothing leaves Page Name blank, so there's
  // nothing to review. (draft is non-null only for an extraction seed.)
  let showRetrievalNote = $derived(sourceType === 'web' && !!draft?.name);

  // A web source's name is the page's; books/magazines just use "Name".
  let nameLabel = $derived(sourceType === 'web' ? 'Page Name' : 'Name');

  // Read-only only for a successful scrape (the URL is confirmed reachable, just
  // for confirmation). A failed scrape (web-url) or manual create keeps it
  // editable — a failed scrape is exactly when the URL may be mistyped.
  let urlReadonly = $derived(seed.kind === 'extraction');

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
        isbn: draft?.isbn ?? null,
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
  {#if showRetrievalNote}
    <div class="extraction-note">Retrieved from page — review before saving</div>
  {/if}
  <TextField label={nameLabel} bind:value={name} bind:inputRef={nameInputEl} noAutofill />
  {#if showAuthorField}
    <TextField label="Author" optional bind:value={author} noAutofill />
  {/if}
  {#if showPublisherField}
    <TextField label="Publisher" optional bind:value={publisher} noAutofill />
  {/if}
  {#if showYearField}
    <!-- Custom (not NumberField): a nullable, optional integer with no spinner. -->
    <FieldGroup label="Year" optional>
      {#snippet children(inputId)}
        <input
          id={inputId}
          type="text"
          inputmode="numeric"
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
      {/snippet}
    </FieldGroup>
  {/if}
  {#if showUrlField}
    <TextField
      label="URL"
      type="url"
      placeholder="https://\u2026"
      readonly={urlReadonly}
      bind:value={url}
      noAutofill
    />
  {/if}
  {#if error}
    <div class="form-error">{error}</div>
  {/if}
  <button type="submit" class="submit-btn" disabled={submitting}>
    {submitting ? 'Creating\u2026' : submitLabel}
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
