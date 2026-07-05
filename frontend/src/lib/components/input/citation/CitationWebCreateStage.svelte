<!-- @component Web site + page create flow (describe-site → page) for a new site, a domain match, or a page under a chosen root. -->
<script lang="ts">
  import client from '$lib/api/client';
  import { hostFromUrl, type CreateSeed } from './citation-types';
  import DropdownButton from '$lib/components/input/dropdown/DropdownButton.svelte';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import TextField from '$lib/components/input/TextField.svelte';

  let {
    seed,
    parentId = null,
    onsourcecreated,
    oncancel,
    onback,
  }: {
    seed: CreateSeed;
    /** The explicitly-chosen parent root — set only on the identify "add a page
     *  under this site" path. When present, finalize files the page directly
     *  under it (honoring the choice) instead of letting `cite-url` re-recognize
     *  the URL. Null for new-site and domain-match pastes, where `cite-url`
     *  resolves the root from the URL. */
    parentId?: number | null;
    onsourcecreated: (result: {
      sourceId: number;
      sourceName: string;
      sourceType: string;
      skipLocator: boolean;
    }) => void;
    oncancel: () => void;
    /** Leaves the web-create flow entirely (back to search). */
    onback: () => void;
  } = $props();

  // The seed is captured once at mount — the orchestrator mounts a fresh
  // component per stage transition, so it won't change (and only ever passes a
  // `web` seed here). `siteName` non-null means the site already exists, so
  // Create Site is skipped; `draft` is the page scrape, or null when it failed.
  // svelte-ignore state_referenced_locally
  const draft = seed.kind === 'web' ? seed.draft : null;
  // svelte-ignore state_referenced_locally
  const existingSiteName = seed.kind === 'web' ? seed.siteName : null;
  // svelte-ignore state_referenced_locally
  const seedUrl = seed.kind === 'web' ? seed.url : '';

  // -----------------------------------------------------------------------
  // Two-panel wizard: describe the site, then confirm the page. An existing
  // site skips the site panel and opens straight on the page.
  // -----------------------------------------------------------------------

  let step = $state<'site' | 'page'>(existingSiteName === null ? 'site' : 'page');

  // Site name is the new root's name (unused for an existing site). Prefill
  // og:site_name (the draft's `publisher` field) when scraped, else the domain —
  // so the field always shows the name the root will get. (The backend
  // independently defaults a blank name to the domain, as a safety net.)
  let siteName = $state(existingSiteName === null ? draft?.publisher || hostFromUrl(seedUrl) : '');
  let siteDescription = $state('');
  // Page name prefills from the scraped og:title, or the seed's explicit
  // `pageName` (the manual "add a page under a known site" path, which has no
  // scrape but carries the text the contributor typed).
  // svelte-ignore state_referenced_locally
  let pageName = $state((seed.kind === 'web' ? seed.pageName : undefined) ?? draft?.name ?? '');
  let url = $state(seedUrl);

  let error = $state('');
  let submitting = $state(false);
  let siteNameInputEl: HTMLInputElement | undefined = $state();
  let pageNameInputEl: HTMLInputElement | undefined = $state();

  // Domain match: the URL's domain recognized to an existing root, but the user
  // didn't explicitly choose it (unlike the identify path). The recognized URL
  // is the one being cited under that root, so it's read-only — letting the host
  // change here would silently re-route the cite (cite-url re-recognizes the
  // edited URL) away from the "Cite a page under X" the UI promises.
  let isDomainMatch = $derived(existingSiteName !== null && parentId === null);

  // Read-only when a successful scrape confirms the URL, or on a domain match
  // (above). Editable for a new site whose scrape failed (the URL may be a typo,
  // and a new host correctly flows through describe-site) and for the identify
  // path (the URL starts blank and the chosen parent is honored regardless).
  let urlReadonly = $derived(draft !== null || isDomainMatch);

  // New site with a failed scrape: the URL is editable, so keep the host-derived
  // site name in step with it until the contributor types their own — otherwise
  // correcting a mistyped URL (typo.example → real.com) would leave the new root
  // named after the old host. (No-op once scraped: the URL is read-only then.)
  let siteNameTouched = $state(false);
  $effect(() => {
    if (existingSiteName === null && draft === null && !siteNameTouched) {
      siteName = hostFromUrl(url);
    }
  });

  // Show the "retrieved" note only when the scrape actually returned a page
  // title to review — an extraction that found nothing leaves Page name blank,
  // so there's nothing to check. (draft is non-null only for an extraction.)
  let showRetrievalNote = $derived(!!draft?.name);

  $effect(() => {
    if (step === 'site') siteNameInputEl?.focus();
    else pageNameInputEl?.focus();
  });

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      oncancel();
    }
  }

  function goNext() {
    error = '';
    step = 'page';
  }

  function goBack() {
    // For a new site the page panel steps back to the site panel; for an
    // existing site the page panel is the only step, so back leaves the flow.
    if (step === 'page' && existingSiteName === null) {
      error = '';
      step = 'site';
    } else {
      onback();
    }
  }

  // Finalize: the one write of the whole flow, so abandoning beforehand writes
  // nothing. With an explicit parent (the identify path), file the page directly
  // under that root via `pages/` — the contributor already chose it, so we don't
  // let the URL re-route it. Otherwise `cite-url` resolves the root from the URL
  // (creating the site root + page child for a new site). Either returns the web
  // child; the orchestrator then auto-submits the instance (skip_locator=true).
  async function finalize() {
    if (!url.trim()) {
      error = 'URL is required.';
      return;
    }
    if (parentId !== null && !pageName.trim()) {
      // The backend would derive a name from the URL, but on the explicit-parent
      // path we ask the contributor to name the page rather than auto-deriving.
      error = 'Page name is required.';
      return;
    }

    submitting = true;
    error = '';

    // Branched (not a ternary) so each call keeps its own response type.
    if (parentId !== null) {
      const { data, error: apiError } = await client.POST(
        '/api/citation-sources/{source_id}/pages/',
        {
          params: { path: { source_id: parentId } },
          body: { url, page_name: pageName },
        },
      );
      finish(data, apiError);
    } else {
      const { data, error: apiError } = await client.POST('/api/citation-sources/cite-url/', {
        body: {
          url,
          site_name: siteName,
          site_description: siteDescription,
          page_name: pageName,
        },
      });
      finish(data, apiError);
    }
  }

  /** Shared tail of both finalize paths: clear the spinner, surface an error, or
   *  emit the created web child for the orchestrator to cite. */
  function finish(
    data: { id: number; name: string; source_type: string; skip_locator: boolean } | undefined,
    apiError: unknown,
  ) {
    submitting = false;
    if (apiError || !data) {
      error = typeof apiError === 'string' ? apiError : 'Failed to create source.';
      return;
    }
    onsourcecreated({
      sourceId: data.id,
      sourceName: data.name,
      sourceType: data.source_type,
      skipLocator: data.skip_locator,
    });
  }
</script>

<DropdownHeader onback={goBack}
  >{existingSiteName === null ? 'New site' : 'New page'}</DropdownHeader
>
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<form
  class="create-form"
  onsubmit={(e) => {
    e.preventDefault();
    if (step === 'site') goNext();
    else finalize();
  }}
  onkeydown={handleKeydown}
>
  {#if step === 'site'}
    <div class="note">This will be the first citation from this domain.</div>
    <TextField
      label="Site name"
      bind:value={siteName}
      bind:inputRef={siteNameInputEl}
      noAutofill
      oninput={() => (siteNameTouched = true)}
    />
    <TextField label="Site description" optional bind:value={siteDescription} noAutofill />
    <DropdownButton type="submit">Next</DropdownButton>
  {:else}
    {#if existingSiteName !== null}
      <div class="note">Cite a page under <strong>{existingSiteName}</strong>.</div>
    {:else if showRetrievalNote}
      <div class="note">Retrieved from page — review before saving</div>
    {/if}
    <TextField
      label="Page name"
      optional
      bind:value={pageName}
      bind:inputRef={pageNameInputEl}
      noAutofill
    />
    <TextField
      label="URL"
      type="url"
      placeholder="https://…"
      readonly={urlReadonly}
      bind:value={url}
      noAutofill
    />
    {#if error}
      <div class="form-error">{error}</div>
    {/if}
    <DropdownButton type="submit" disabled={submitting}>
      {submitting ? 'Creating…' : 'Create Citation'}
    </DropdownButton>
  {/if}
</form>

<style>
  .create-form {
    padding: var(--size-2) var(--size-3);
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .note {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    font-style: italic;
  }

  .form-error {
    color: var(--color-error-text);
    font-size: var(--font-size-0);
  }
</style>
