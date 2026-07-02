<script lang="ts" generics="T extends { slug: string; name: string }">
  import type { Snippet } from 'svelte';
  import { goto } from '$app/navigation';
  import Button from '$lib/components/ui/Button.svelte';
  import NotesAndCitationsDetails from '$lib/components/input/citation/NotesAndCitationsDetails.svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import { buildEditCitationsRequest, type EditCitationSelection } from '$lib/edit-citation';
  import { pageTitle } from '$lib/constants';
  import { resolveHref } from '$lib/utils';
  import { classifyCreateResponse, reconcileSlug, slugifyForCatalog } from '$lib/create-form';
  import { toast } from '$lib/toast/toast.svelte';

  type SubmitBody = {
    name: string;
    slug: string;
    note: string;
    citations: ReturnType<typeof buildEditCitationsRequest>;
    [extra: string]: unknown;
  };

  type SubmitResult = {
    data?: T | undefined;
    error?: unknown;
    response: Response;
  };

  type ExtraBodyResult = Record<string, unknown> | { error: string } | null;

  type Props = {
    entityLabel: string;
    heading?: string;
    initialName: string;
    submit: (body: SubmitBody) => Promise<SubmitResult>;
    detailHref: (slug: string) => string;
    cancelHref: string;
    parentBreadcrumb?: { text: string; href: string };
    projectSlug?: (name: string) => string;
    notePlaceholder?: string;
    /**
     * Field keys whose server-side errors should route to the caller
     * (via the `errors` arg on the `extraFields` snippet). Any field
     * error whose key is NOT in this set or `{name, slug}` falls through
     * to the top-level `formError` as today.
     */
    extraFieldKeys?: readonly string[];
    /**
     * Extra form fields rendered between the built-in Name/Slug block and
     * the notes/citations details. The snippet receives a reactive `errors`
     * record keyed by `extraFieldKeys`, cleared on each submit.
     */
    extraFields?: Snippet<[{ disabled: boolean; errors: Record<string, string> }]>;
    /**
     * Called at submit time to collect extra body fields. Return an
     * object to merge into the request body, `{ error }` to block
     * submission with a form-level error, or null/undefined for no
     * extras.
     */
    extraBody?: () => ExtraBodyResult | undefined;
  };

  let {
    entityLabel,
    heading,
    initialName,
    submit,
    detailHref,
    cancelHref,
    parentBreadcrumb,
    projectSlug,
    notePlaceholder,
    extraFieldKeys,
    extraFields,
    extraBody,
  }: Props = $props();

  let extraErrors = $state<Record<string, string>>({});

  const project = (value: string) => (projectSlug ? projectSlug(value) : slugifyForCatalog(value));

  const headingText = $derived(heading ?? `New ${entityLabel}`);

  // svelte-ignore state_referenced_locally
  const initialSlug = project(initialName);
  // svelte-ignore state_referenced_locally
  let name = $state(initialName);
  let slug = $state(initialSlug);
  let syncedSlug = $state(initialSlug);
  let note = $state('');
  let citation = $state<EditCitationSelection | null>(null);

  let formError = $state('');
  let nameError = $state('');
  let slugError = $state('');
  let submitting = $state(false);

  $effect(() => {
    const next = reconcileSlug({ name, slug, syncedSlug, projectedSlug: project(name) });
    if (next.slug !== slug) {
      slug = next.slug;
      syncedSlug = next.syncedSlug;
    }
  });

  async function handleSave() {
    formError = '';
    nameError = '';
    slugError = '';
    extraErrors = {};

    if (!name.trim()) {
      nameError = 'Name cannot be blank.';
      return;
    }
    if (!slug.trim()) {
      slugError = 'Slug cannot be blank.';
      return;
    }

    let extras: Record<string, unknown> = {};
    if (extraBody) {
      const result = extraBody();
      if (result && 'error' in result && typeof result.error === 'string') {
        formError = result.error;
        return;
      }
      if (result) {
        extras = result as Record<string, unknown>;
      }
    }

    submitting = true;
    try {
      const {
        data: created,
        error,
        response,
      } = await submit({
        name: name.trim(),
        // Slugs are lowercase-only — casefold at submit so users see what
        // they typed while authoring and the backend SLUG_RE validator
        // never trips.
        slug: slug.trim().toLowerCase(),
        note: note || '',
        citations: buildEditCitationsRequest(citation),
        ...extras,
      });

      const outcome = classifyCreateResponse({ data: created, error, response });
      switch (outcome.kind) {
        case 'ok':
          toast.success(`Created “${outcome.data.name}”.`, { persistUntilNav: true });
          await goto(resolveHref(detailHref(outcome.slug)));
          return;
        case 'rate_limited':
          formError = outcome.message;
          return;
        case 'field_errors': {
          nameError = outcome.fieldErrors.name ?? '';
          slugError = outcome.fieldErrors.slug ?? '';
          const nextExtra: Record<string, string> = {};
          for (const key of extraFieldKeys ?? []) {
            const msg = outcome.fieldErrors[key];
            if (msg) nextExtra[key] = msg;
          }
          extraErrors = nextExtra;
          const hasExtra = Object.keys(nextExtra).length > 0;
          if (!nameError && !slugError && !hasExtra) {
            formError = outcome.message;
          }
          return;
        }
        case 'form_error':
          formError = outcome.message;
          return;
      }
    } finally {
      submitting = false;
    }
  }

  function handleCancel() {
    goto(resolveHref(cancelHref));
  }
</script>

<svelte:head>
  <title>{pageTitle(headingText)}</title>
</svelte:head>

<div class="create-page">
  <header class="hdr">
    {#if parentBreadcrumb}
      <p class="parent-breadcrumb">
        <a href={resolveHref(parentBreadcrumb.href)}>{parentBreadcrumb.text}</a>
      </p>
    {/if}
    <h1>{headingText}</h1>
  </header>

  {#if formError}
    <p class="save-error" role="alert">{formError}</p>
  {/if}

  <div class="fields">
    <TextField label="Name" bind:value={name} error={nameError} />
    <TextField
      label="Slug"
      bind:value={slug}
      error={slugError}
      placeholder="lowercase-hyphenated"
    />
    {#if extraFields}
      {@render extraFields({ disabled: submitting, errors: extraErrors })}
    {/if}
  </div>

  <NotesAndCitationsDetails
    bind:note
    bind:citation
    noteLabel="Creation note"
    notePlaceholder={notePlaceholder ?? `Why are you adding this ${entityLabel.toLowerCase()}?`}
  />

  <div class="form-footer">
    <Button variant="secondary" onclick={handleCancel}>Cancel</Button>
    <Button onclick={handleSave} disabled={submitting}>
      {submitting ? 'Creating…' : `Create ${entityLabel}`}
    </Button>
  </div>
</div>

<style>
  .create-page {
    max-width: 36rem;
    margin: 0 auto;
    padding: var(--size-6) var(--size-5);
    display: flex;
    flex-direction: column;
    gap: var(--size-4);
  }

  .hdr h1 {
    margin: 0 0 var(--size-2);
  }

  .parent-breadcrumb {
    margin: 0 0 var(--size-1);
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }

  .parent-breadcrumb a {
    color: var(--color-text-muted);
    text-decoration: none;
  }

  .parent-breadcrumb a:hover {
    color: var(--color-text);
    text-decoration: underline;
  }

  .save-error {
    color: var(--color-error-text);
    font-size: var(--font-size-1);
    margin: 0;
  }

  .fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .form-footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--size-3);
    margin-top: var(--size-4);
    padding-top: var(--size-3);
    border-top: 1px solid var(--color-border-soft);
  }
</style>
