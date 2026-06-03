<script lang="ts">
  import client from '$lib/api/client';
  import {
    transition,
    isDraftSubmittable,
    emptyDraft,
    type CiteState,
    type CiteAction,
    type CitationInstanceDraft,
    type CitationSourceResult,
    type ExtractionDraft,
  } from './citation-types';
  import CitationSearchStage from './CitationSearchStage.svelte';
  import CitationIdentifyBySearchStage from './CitationIdentifyBySearchStage.svelte';
  import CitationCreateStage from './CitationCreateStage.svelte';
  import CitationLocatorStage from './CitationLocatorStage.svelte';

  let {
    oncomplete,
    oncancel,
    onback,
  }: {
    oncomplete: (linkText: string) => void;
    oncancel: () => void;
    onback: () => void;
  } = $props();

  let flow: CiteState = $state({ stage: 'search', draft: emptyDraft() });
  let isSubmitting = $state(false);
  let submitError = $state('');

  // -------------------------------------------------------------------
  // Submission — single place that creates the citation instance
  // -------------------------------------------------------------------

  async function submit(draft: CitationInstanceDraft) {
    if (isSubmitting || draft.sourceId === null) return;
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

    oncomplete(`[[cite:${data.id}]]`);
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

  function handleSourceCreateStarted(prefillName: string) {
    dispatch({ type: 'source_create_started', prefillName });
  }

  function handleExtractionDraft(extractionDraft: ExtractionDraft) {
    dispatch({ type: 'extraction_draft_ready', extractionDraft });
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
      onsourcecreatestarted={handleSourceCreateStarted}
      onextractiondraft={handleExtractionDraft}
      {oncancel}
      onback={handleBack}
    />
  {:else if flow.stage === 'identify'}
    <CitationIdentifyBySearchStage
      parentContext={flow.parent}
      onsourceidentified={handleSourceIdentified}
      onsourcecreatestarted={handleSourceCreateStarted}
      {oncancel}
      onback={goBackToSearch}
    />
  {:else if flow.stage === 'create'}
    <CitationCreateStage
      parentContext={flow.parent}
      prefillName={flow.prefillName}
      extractionDraft={flow.extractionDraft}
      onsourcecreated={handleSourceCreated}
      {oncancel}
      onback={goBackToSearch}
    />
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
