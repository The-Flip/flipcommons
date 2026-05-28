<script lang="ts">
  import type { ChangeSetDetailSchema, ChangeSetSummarySchema } from '$lib/api/schema';
  import client from '$lib/api/client';
  import { CATALOG_META } from '$lib/models/model-meta';
  import { SITE_TITLE } from '$lib/constants';
  import { resolveHref } from '$lib/utils';
  import ClaimAttribution from '$lib/components/ClaimAttribution.svelte';
  import ClaimValue from '$lib/components/ClaimValue.svelte';
  import InlineDiff from '$lib/components/InlineDiff.svelte';
  import { SvelteMap, SvelteSet } from 'svelte/reactivity';
  import { isDiffable } from '$lib/components/change-display';
  import { changesLabel } from './changes';

  type ChangeSetSummary = ChangeSetSummarySchema;
  type ChangeSetDetail = ChangeSetDetailSchema;

  // Filter state
  let entityType = $state('');
  let timeRange = $state('');

  // Feed state
  let items = $state<ChangeSetSummary[]>([]);
  let nextCursor = $state<string | null>(null);
  let loading = $state(false);
  let loadingMore = $state(false);
  let error = $state('');
  let fetchGeneration = 0;

  // Detail cache (changeset diffs are immutable)
  let detailCache = new SvelteMap<number, ChangeSetDetail>();
  let expandedIds = new SvelteSet<number>();
  let loadingDetailIds = new SvelteSet<number>();

  // Sentinel for infinite scroll
  let sentinel: HTMLDivElement | undefined = $state();

  function computeTimeFilter(): { after?: string; before?: string } {
    if (!timeRange) return {};
    const now = new Date();
    const ms: Record<string, number> = {
      '24h': 24 * 60 * 60 * 1000,
      '7d': 7 * 24 * 60 * 60 * 1000,
      '30d': 30 * 24 * 60 * 60 * 1000,
    };
    if (ms[timeRange]) {
      return { after: new Date(now.getTime() - ms[timeRange]).toISOString() };
    }
    return {};
  }

  async function fetchPage(cursor?: string) {
    const { after, before } = computeTimeFilter();
    const { data } = await client.GET('/api/pages/changesets/', {
      params: {
        query: {
          entity_type: entityType || undefined,
          after,
          before,
          cursor: cursor || undefined,
          limit: 50,
        },
      },
    });
    return data;
  }

  async function loadInitial() {
    const gen = ++fetchGeneration;
    loading = true;
    loadingMore = false;
    error = '';
    expandedIds.clear();
    detailCache.clear();
    try {
      const data = await fetchPage();
      if (gen !== fetchGeneration) return;
      if (data) {
        items = data.items;
        nextCursor = data.next_cursor ?? null;
      } else {
        error = 'Failed to load changes.';
      }
    } catch {
      if (gen !== fetchGeneration) return;
      error = 'Failed to load changes.';
    } finally {
      if (gen === fetchGeneration) loading = false;
    }
  }

  async function loadMore() {
    if (loadingMore || !nextCursor) return;
    const gen = fetchGeneration;
    loadingMore = true;
    try {
      const data = await fetchPage(nextCursor);
      if (gen !== fetchGeneration) return;
      if (data) {
        items = [...items, ...data.items];
        nextCursor = data.next_cursor ?? null;
      }
    } finally {
      if (gen === fetchGeneration) loadingMore = false;
    }
  }

  async function toggleDetail(id: number) {
    if (expandedIds.has(id)) {
      expandedIds.delete(id);
      return;
    }

    if (!detailCache.has(id)) {
      loadingDetailIds.add(id);
      try {
        const { data } = await client.GET('/api/pages/changesets/{changeset_id}/', {
          params: { path: { changeset_id: id } },
        });
        if (data) {
          detailCache.set(id, data);
        }
      } finally {
        loadingDetailIds.delete(id);
      }
    }

    if (detailCache.has(id)) {
      expandedIds.add(id);
    }
  }

  // Reload on filter change
  let filterKey = $derived(`${entityType}|${timeRange}`);

  $effect(() => {
    // Read filterKey to trigger on any filter change
    void filterKey;
    loadInitial();
  });

  // Infinite scroll sentinel
  $effect(() => {
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMore();
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  });
</script>

<svelte:head>
  <title>Changelog &mdash; {SITE_TITLE}</title>
</svelte:head>

<div class="changes-page">
  <header class="page-header">
    <h1>Changelog</h1>
  </header>

  <div class="filter-bar">
    <label class="filter-field">
      <span class="filter-label">Entity type</span>
      <select bind:value={entityType}>
        <option value="">All types</option>
        {#each Object.values(CATALOG_META) as et (et.entity_type)}
          <option value={et.entity_type}>{et.label}</option>
        {/each}
      </select>
    </label>

    <label class="filter-field">
      <span class="filter-label">Time range</span>
      <select bind:value={timeRange}>
        <option value="">All time</option>
        <option value="24h">Last 24 hours</option>
        <option value="7d">Last 7 days</option>
        <option value="30d">Last 30 days</option>
      </select>
    </label>
  </div>

  {#if loading}
    <p class="status-message">Loading...</p>
  {:else if error}
    <p class="status-message error">{error}</p>
  {:else if items.length === 0}
    <p class="status-message">No changes found.</p>
  {:else}
    <ol class="feed">
      {#each items as cs (cs.id)}
        <li class="feed-item">
          <div class="feed-header">
            <a href={resolveHref(cs.entity.href)} class="entity-link">
              <span class="entity-name">{cs.entity.name}</span>
              <span class="entity-type">{cs.entity.type_label}</span>
            </a>
            <span class="byline">
              By <ClaimAttribution attribution={cs.attribution} />
            </span>
          </div>

          <div class="feed-body">
            <span class="changes-count">{changesLabel(cs)}</span>
            {#if cs.note}
              <p class="feed-note">{cs.note}</p>
            {/if}
          </div>

          <button
            class="expand-toggle"
            onclick={() => toggleDetail(cs.id)}
            disabled={loadingDetailIds.has(cs.id)}
          >
            {#if loadingDetailIds.has(cs.id)}
              Loading...
            {:else if expandedIds.has(cs.id)}
              Hide changes &#9662;
            {:else}
              Show changes &#9656;
            {/if}
          </button>

          {#if expandedIds.has(cs.id) && detailCache.has(cs.id)}
            {@const detail = detailCache.get(cs.id)!}
            <div class="detail-panel">
              {#if detail.changes.length > 0}
                <dl class="field-list">
                  {#each detail.changes as change (change.claim_key)}
                    {#if isDiffable(change)}
                      <div class="field-row field-row-diff">
                        <dt>{change.field_name}</dt>
                        <dd>
                          <InlineDiff
                            oldValue={change.old_value.raw}
                            newValue={change.new_value.raw}
                          />
                        </dd>
                      </div>
                    {:else}
                      <div class="field-row">
                        <dt>{change.field_name}</dt>
                        <dd>
                          {#if change.old_value != null}
                            <span class="old-value claim-value-inline"
                              ><ClaimValue value={change.old_value} /></span
                            >
                            <span class="arrow">&rarr;</span>
                          {/if}
                          <span class="new-value claim-value-inline"
                            ><ClaimValue value={change.new_value} /></span
                          >
                        </dd>
                      </div>
                    {/if}
                  {/each}
                </dl>
              {/if}

              {#if detail.retractions.length > 0}
                <dl class="field-list retractions">
                  {#each detail.retractions as retraction (retraction.claim_key)}
                    <div class="field-row">
                      <dt>{retraction.field_name}</dt>
                      <dd>
                        <span class="retraction-label">Removed</span>
                        <span class="old-value claim-value-inline"
                          ><ClaimValue value={retraction.old_value} /></span
                        >
                      </dd>
                    </div>
                  {/each}
                </dl>
              {/if}

              {#if detail.changes.length === 0 && detail.retractions.length === 0}
                <p class="no-changes">No field-level changes recorded.</p>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ol>

    {#if nextCursor}
      <div class="sentinel" bind:this={sentinel}>
        {#if loadingMore}
          <p class="status-message">Loading more...</p>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .changes-page {
    padding: var(--size-5) 0;
  }

  .page-header {
    margin-bottom: var(--size-4);
  }

  .page-header h1 {
    font-size: var(--font-size-5);
    font-weight: 700;
    color: var(--color-text);
    margin: 0;
  }

  /* Filter bar */
  .filter-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--size-3);
    margin-bottom: var(--size-5);
    padding: var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background-color: var(--color-surface);
  }

  .filter-field {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .filter-label {
    font-size: var(--font-size-0);
    font-weight: 500;
    color: var(--color-text-muted);
  }

  .filter-field select {
    padding: var(--size-1) var(--size-2);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-1);
    background-color: var(--color-surface);
    color: var(--color-text);
    font-size: var(--font-size-1);
  }

  /* Feed list */
  .feed {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .feed-item {
    padding: var(--size-3) 0;
    border-bottom: 1px solid var(--color-border-soft);
  }

  .feed-item:last-child {
    border-bottom: none;
  }

  .feed-header {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--size-2);
  }

  .byline {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin-left: auto;
    white-space: nowrap;
  }

  .entity-link {
    display: inline-flex;
    align-items: baseline;
    gap: var(--size-2);
    text-decoration: none;
    color: var(--color-text);
  }

  .entity-link:hover .entity-name {
    color: var(--color-link);
  }

  .entity-name {
    font-weight: 500;
  }

  .entity-type {
    font-size: var(--font-size-00, 0.7rem);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--color-text-muted);
    padding: 1px var(--size-2);
    border-radius: var(--radius-1);
    background-color: var(--color-surface);
    border: 1px solid var(--color-border-soft);
  }

  .feed-body {
    margin-top: var(--size-1);
  }

  .changes-count {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .feed-note {
    font-size: var(--font-size-0);
    font-style: italic;
    color: var(--color-text-muted);
    margin: var(--size-1) 0 0 0;
  }

  /* Expand/collapse toggle */
  .expand-toggle {
    background: none;
    border: none;
    color: var(--color-link);
    font-size: var(--font-size-0);
    padding: var(--size-1) 0 0;
    cursor: pointer;
  }

  .expand-toggle:hover {
    text-decoration: underline;
  }

  .expand-toggle:disabled {
    color: var(--color-text-muted);
    cursor: default;
    text-decoration: none;
  }

  /* Detail panel */
  .detail-panel {
    margin-top: var(--size-2);
    padding: var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background-color: var(--color-surface);
  }

  .field-list {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0;
  }

  .field-row {
    display: flex;
    gap: var(--size-3);
    padding: var(--size-1) 0;
    border-bottom: 1px solid var(--color-border-soft);
    font-size: var(--font-size-0);
  }

  .field-row:last-child {
    border-bottom: none;
  }

  .field-row dt {
    min-width: 10rem;
    font-weight: 500;
    color: var(--color-text-muted);
  }

  .field-row dd {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--size-1);
    color: var(--color-text);
    overflow-wrap: break-word;
  }

  .field-row-diff {
    flex-wrap: wrap;
  }

  .field-row-diff dd {
    flex-basis: 100%;
    display: block;
  }

  .old-value {
    text-decoration: line-through;
    opacity: 0.5;
  }

  .arrow {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  .new-value {
    font-weight: 500;
  }

  .claim-value-inline {
    display: inline-block;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: bottom;
  }

  /* Retractions */
  .retractions {
    margin-top: var(--size-2);
  }

  .retraction-label {
    font-weight: 600;
    color: var(--color-error-text);
    font-size: var(--font-size-00, 0.7rem);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 1px var(--size-2);
    border-radius: var(--radius-1);
    background-color: color-mix(in srgb, var(--color-error-text) 10%, transparent);
  }

  /* Status messages */
  .status-message {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    padding: var(--size-4) 0;
  }

  .status-message.error {
    color: var(--color-error-text);
  }

  .no-changes {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .sentinel {
    height: 1px;
  }

  @media (--breakpoint-narrow) {
    .filter-bar {
      flex-direction: column;
      align-items: stretch;
    }

    .byline {
      margin-left: 0;
    }

    .field-row {
      flex-direction: column;
      gap: var(--size-1);
    }

    .field-row dt {
      min-width: unset;
    }
  }
</style>
