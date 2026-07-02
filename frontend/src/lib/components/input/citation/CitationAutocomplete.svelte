<!-- @component Orchestrates the citation create/cite flow across its stages. -->
<script lang="ts">
  import client from '$lib/api/client';
  import {
    transition,
    isDraftSubmittable,
    isWebSeed,
    emptyDraft,
    type CitationCompletion,
    type CiteState,
    type CiteAction,
    type CitationInstanceDraft,
    type CitationSourceResult,
    type CreateSeed,
  } from './citation-types';
  import CitationSearchStage from './CitationSearchStage.svelte';
  import CitationIdentifyBySearchStage from './CitationIdentifyBySearchStage.svelte';
  import CitationCreateStage from './CitationCreateStage.svelte';
  import CitationWebCreateStage from './CitationWebCreateStage.svelte';
  import CitationLocatorStage from './CitationLocatorStage.svelte';

  let {
    completion,
    oncancel,
    onback,
  }: {
    /** What happens when the flow completes — see {@link CitationCompletion}. */
    completion: CitationCompletion;
    oncancel: () => void;
    onback: () => void;
  } = $props();

  let flow: CiteState = $state({ stage: 'search', draft: emptyDraft() });
  let isSubmitting = $state(false);
  let submitError = $state('');

  // -------------------------------------------------------------------
  // Submission — hands the completed draft to the consumer, minting the
  // instance first only for the inline flow (it needs the slug now)
  // -------------------------------------------------------------------

  async function submit(draft: CitationInstanceDraft) {
    if (isSubmitting || draft.sourceId === null) return;

    if (completion.kind === 'content-spec') {
      completion.oncomplete({
        sourceId: draft.sourceId,
        sourceName: draft.sourceName,
        locator: draft.locator,
      });
      return;
    }

    isSubmitting = true;
    submitError = '';

    const { data, error } = await client.POST('/api/citation-instances/', {
      body: { citation_source_id: draft.sourceId, locator: draft.locator },
    });

    isSubmitting = false;

    if (error) {
      submitError = 'Failed to create citation.';
      return;
    }

    completion.oncomplete(data);
  }

  /** Dispatch an action, then auto-submit if the draft is ready. */
  function dispatch(action: CiteAction) {
    if (isSubmitting) return;
    flow = transition(flow, action);
    if (isDraftSubmittable(flow.draft)) {
      submit(flow.draft);
    }
  }

  function goBackToSearch() {
    if (isSubmitting) return;
    flow = { stage: 'search', draft: emptyDraft() };
  }

  // -------------------------------------------------------------------
  // Stage callbacks
  // -------------------------------------------------------------------

  function handleSourceSelected(source: CitationSourceResult) {
    dispatch({ type: 'source_selected', source });
  }

  function handleSourceIdentified(child: {
    sourceId: number;
    sourceName: string;
    skipLocator: boolean;
  }) {
    dispatch({ type: 'source_identified', ...child });
  }

  function handleCreateStarted(seed: CreateSeed) {
    dispatch({ type: 'create_started', seed });
  }

  function handleSourceCreated(result: {
    sourceId: number;
    sourceName: string;
    skipLocator: boolean;
  }) {
    dispatch({ type: 'source_created', ...result });
  }

  function handleLocatorSubmit(locator: string) {
    if (isSubmitting) return;
    flow = transition(flow, { type: 'locator_submitted', locator });
    submit(flow.draft);
  }

  function handleBack() {
    if (isSubmitting) return;
    if (flow.stage === 'search') {
      onback();
    } else {
      goBackToSearch();
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div onkeydown={(e) => e.stopPropagation()}>
  {#if submitError}
    <div class="submit-error">{submitError}</div>
  {/if}

  {#if flow.stage === 'search'}
    <CitationSearchStage
      onsourceselected={handleSourceSelected}
      onsourceidentified={handleSourceIdentified}
      oncreatestarted={handleCreateStarted}
      {oncancel}
      onback={handleBack}
    />
  {:else if flow.stage === 'identify'}
    <CitationIdentifyBySearchStage
      parentContext={flow.parent}
      onsourceidentified={handleSourceIdentified}
      oncreatestarted={handleCreateStarted}
      {oncancel}
      onback={goBackToSearch}
    />
  {:else if flow.stage === 'create'}
    <!-- A pasted web URL gets the describe-site → page web flow (the seed says
         whether the site is new or already exists); books and magazines use the
         authored-work form. -->
    {#if isWebSeed(flow.seed)}
      <!-- flow.parent is set only when the create was started from the identify
           stage (an explicit "add a page under this root"); search-started web
           pastes (new site, domain match) carry no parent and let cite-url
           resolve the root. -->
      <CitationWebCreateStage
        seed={flow.seed}
        parentId={flow.parent?.id ?? null}
        onsourcecreated={handleSourceCreated}
        {oncancel}
        onback={goBackToSearch}
      />
    {:else}
      <CitationCreateStage
        parentContext={flow.parent}
        seed={flow.seed}
        onsourcecreated={handleSourceCreated}
        {oncancel}
        onback={goBackToSearch}
      />
    {/if}
  {:else if flow.stage === 'locator'}
    <CitationLocatorStage
      draft={flow.draft}
      onsubmit={handleLocatorSubmit}
      {oncancel}
      onback={goBackToSearch}
    />
  {/if}
</div>

<style>
  .submit-error {
    padding: var(--size-2) var(--size-3);
    color: var(--color-error-text);
    font-size: var(--font-size-0);
    text-align: center;
  }
</style>
