<!-- @component New-source form for an authored work — book, periodical, or video/movie (a root, or an edition under a parent). -->
<script lang="ts">
  import client from '$lib/api/client';
  import type { ParentContext, CreateSeed } from './citation-types';
  import { citationTypeMeta } from '$lib/citation-types';
  import { CITATION_TYPE_META } from '$lib/citation-types/citation-type-meta';
  import DropdownButton from '$lib/components/input/dropdown/DropdownButton.svelte';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import { reconcileSlug, slugifyForCatalog } from '$lib/create-form';

  type SourceType = 'book' | 'periodical' | 'video';

  /** The types the picker offers: exactly those whose roots are authored here.
   *  Web is absent because its flag is off — sites are created by pasting a
   *  URL (CitationWebCreateStage), never typed in here. */
  const rootCreatableTypes = Object.values(CITATION_TYPE_META)
    .filter((m) => m.authoredRootCreation)
    .map((m) => m.key);

  /** The slug column's limit (CITATION_SOURCE_SLUG_MAX_LENGTH backend-side).
   *  Names run to 500 chars, so an unclamped proposal could exceed what the
   *  API accepts and fail with a generic error. */
  const SLUG_MAX_LENGTH = 200;

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
      sourceType: string;
      skipLocator: boolean;
      isAbstract?: boolean;
      author?: string;
    }) => void;
    oncancel: () => void;
    onback: () => void;
  } = $props();

  // These props are intentionally captured once at mount — the orchestrator
  // creates a fresh component for each stage transition, so they won't change.
  // This stage creates authored works (book/periodical/video) — a root, or an
  // edition under a parent. All web creation goes through
  // CitationWebCreateStage, so a `web` seed never arrives here and an
  // `extraction` seed is always a book.
  // svelte-ignore state_referenced_locally
  const draft = seed.kind === 'extraction' ? seed.draft : null;

  // svelte-ignore state_referenced_locally
  let name = $state(seed.kind === 'name' ? seed.name : (draft?.name ?? ''));
  // A `name` seed may carry a preselected type — the deliverer handoff sets it
  // from the backend's suggested_source_type ("cite the movie itself" →
  // video preselected); the picker stays visible so the user can override.
  // svelte-ignore state_referenced_locally
  let sourceType = $state<SourceType>(
    draft
      ? (draft.source_type as SourceType)
      : parentContext
        ? (parentContext.source_type as SourceType)
        : seed.kind === 'name' && seed.sourceType
          ? (seed.sourceType as SourceType)
          : 'book',
  );
  // svelte-ignore state_referenced_locally
  let author = $state(draft?.author ?? parentContext?.author ?? '');
  let publisher = $state(draft?.publisher ?? '');
  let year = $state<number | null>(draft?.year ?? null);
  let slug = $state('');
  let syncedSlug = $state('');
  let error = $state('');
  let submitting = $state(false);
  let nameInputEl: HTMLInputElement | undefined = $state();

  // The picker shows only for a manual 'name' seed with no parent; a parent or
  // a scrape locks the type.
  let showTypePicker = $derived(seed.kind === 'name' && !parentContext);
  // Publisher and Year come only from a (book) extraction draft.
  let showExtractedFields = $derived(seed.kind === 'extraction');
  // Year is also prompted for a manually-created video: a movie's year is its
  // main disambiguator across remakes.
  let showYear = $derived(showExtractedFields || sourceType === 'video');
  // A slug-addressed type (periodical, per the generated meta — never a
  // hardcoded type name) requires an authored cite handle.
  let slugAddressed = $derived(citationTypeMeta(sourceType).slugAddressed);

  // Auto-propose the slug from the name (shared sync-until-diverged behavior)
  // so the citation flow inherits create-form's slugify instead of its own
  // copy — clamped to the column limit, with the cut never leaving a
  // trailing hyphen (the grammar rejects one).
  $effect(() => {
    if (!slugAddressed) return;
    const projectedSlug = slugifyForCatalog(name).slice(0, SLUG_MAX_LENGTH).replace(/-+$/, '');
    const next = reconcileSlug({ name, slug, syncedSlug, projectedSlug });
    if (next.slug !== slug) {
      slug = next.slug;
      syncedSlug = next.syncedSlug;
    }
  });

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
    if (slugAddressed && !slug.trim()) {
      error = 'Slug is required.';
      return;
    }

    submitting = true;
    error = '';

    const { data, error: apiError } = await client.POST('/api/citation-sources/', {
      body: {
        name,
        source_type: sourceType,
        author,
        publisher: showExtractedFields ? publisher : '',
        year: year ?? null,
        date_note: '',
        isbn: draft?.isbn ?? null,
        description: '',
        parent_id: parentContext?.id ?? null,
        slug: slugAddressed ? slug : null,
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
      sourceType: data.source_type,
      skipLocator: data.skip_locator,
      // An abstract result (a parentless periodical) routes the flow to child
      // identification under it; author rides along for the parent context.
      isAbstract: data.is_abstract,
      author: data.author,
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
      <!-- A video here is a movie (a standalone work); platform videos mint
           from their URLs. -->
      {#each rootCreatableTypes as t (t)}
        <button
          type="button"
          class="type-chip"
          class:selected={sourceType === t}
          onpointerdown={(e) => {
            e.preventDefault();
            sourceType = t as SourceType;
          }}
        >
          {citationTypeMeta(t).label}
        </button>
      {/each}
    </div>
  {/if}
  <TextField label="Name" bind:value={name} bind:inputRef={nameInputEl} noAutofill />
  {#if slugAddressed}
    <!-- The authored cite handle (billboard, 1945-09-29) — auto-proposed from
         the name until the user diverges it. -->
    <TextField label="Slug" bind:value={slug} noAutofill maxlength={SLUG_MAX_LENGTH} />
  {/if}
  <TextField label="Author" optional bind:value={author} noAutofill />
  {#if showExtractedFields}
    <TextField label="Publisher" optional bind:value={publisher} noAutofill />
  {/if}
  {#if showYear}
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
  {#if error}
    <div class="form-error">{error}</div>
  {/if}
  <DropdownButton type="submit" disabled={submitting}>
    {submitting ? 'Creating\u2026' : 'Continue'}
  </DropdownButton>
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

  .form-error {
    color: var(--color-error-text);
    font-size: var(--font-size-0);
  }
</style>
