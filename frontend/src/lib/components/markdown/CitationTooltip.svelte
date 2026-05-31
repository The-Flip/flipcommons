<script lang="ts">
  import { SvelteMap } from 'svelte/reactivity';
  import client from '$lib/api/client';
  import { floating } from '$lib/actions/floating';
  import {
    reduceTooltip,
    type CitationInfo,
    type InlineCitation,
    type TooltipState,
  } from './citation-tooltip';
  import { buildCitationMap } from './citation-refs';

  let {
    container,
    htmlSignal,
    citations = undefined,
    onNavigate = undefined,
  }: {
    container: HTMLDivElement | undefined;
    htmlSignal: string;
    citations?: InlineCitation[];
    onNavigate?: (index: number) => void;
  } = $props();

  let citationData = new SvelteMap<number, CitationInfo>();

  // Populate from prop data when available
  $effect(() => {
    if (citations) {
      const map = buildCitationMap(citations);
      for (const [id, info] of map) {
        citationData.set(id, info);
      }
    }
  });
  let tipState: TooltipState = $state({ activeId: null, pinned: false });
  let tooltipEl: HTMLDivElement | undefined = $state();
  let hideTimer: ReturnType<typeof setTimeout> | null = null;

  const HIDE_DELAY = 100;

  // Clear pending hide timer on unmount
  $effect(() => {
    return () => {
      if (hideTimer != null) clearTimeout(hideTimer);
    };
  });

  let activeCitation = $derived(
    tipState.activeId != null ? citationData.get(tipState.activeId) : null,
  );

  function dispatch(action: Parameters<typeof reduceTooltip>[1]) {
    const result = reduceTooltip(tipState, action);
    if (result.activeId !== tipState.activeId || result.pinned !== tipState.pinned) {
      tipState = { activeId: result.activeId, pinned: result.pinned };
    }

    if (result.cancelHide && hideTimer != null) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
    if (result.scheduleHide) {
      if (hideTimer != null) clearTimeout(hideTimer);
      hideTimer = setTimeout(() => {
        tipState = { activeId: null, pinned: false };
        hideTimer = null;
      }, HIDE_DELAY);
    }
    return result;
  }

  // Track the current anchor element so `floating` can reposition against it.
  let currentAnchor: HTMLElement | null = $state(null);

  // Drop the anchor reference once the tooltip is hidden so we don't retain a
  // pointer to a `<sup>` that may be replaced when the surrounding HTML rerenders.
  $effect(() => {
    if (tipState.activeId == null) currentAnchor = null;
  });

  // Click outside handler
  $effect(() => {
    if (!tipState.pinned) return;

    function onClick(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (tooltipEl?.contains(target)) return;
      if (target.closest('sup[data-cite-id]')) return;
      dispatch({ type: 'click-outside' });
    }
    document.addEventListener('click', onClick, true);
    return () => document.removeEventListener('click', onClick, true);
  });

  // Scan container for citation elements and attach listeners
  $effect(() => {
    void htmlSignal; // re-run when html changes
    if (!container) return;

    const sups = container.querySelectorAll<HTMLElement>('sup[data-cite-id]');
    if (sups.length === 0) return;

    // Collect IDs and fetch missing data (skip if populated from props)
    if (!citations) {
      const idsToFetch: number[] = [];
      for (const sup of sups) {
        const id = Number(sup.dataset.citeId);
        if (!isNaN(id) && !citationData.has(id)) {
          idsToFetch.push(id);
        }
      }
      if (idsToFetch.length > 0) {
        const uniqueIds = [...new Set(idsToFetch)];
        client
          .GET('/api/citation-instances/batch/', {
            params: { query: { ids: uniqueIds.join(',') } },
          })
          .then(({ data }) => {
            if (!data) return;
            for (const item of data) {
              citationData.set(item.id, item as CitationInfo);
            }
          });
      }
    }

    // Attach event listeners
    const cleanups: Array<() => void> = [];

    for (const sup of sups) {
      const id = Number(sup.dataset.citeId);
      if (isNaN(id)) continue;

      const onMouseenter = () => {
        currentAnchor = sup;
        dispatch({ type: 'mouseenter', id });
      };
      const onMouseleave = () => dispatch({ type: 'mouseleave', id });
      const navigateToRef = () => {
        const cite = citations?.find((c) => c.id === id);
        if (cite && onNavigate) {
          dispatch({ type: 'navigate', id });
          onNavigate(cite.index);
        } else {
          dispatch({ type: 'click', id });
        }
      };
      const onClick = (e: Event) => {
        e.preventDefault();
        currentAnchor = sup;
        const pointerType = (e as PointerEvent).pointerType;
        if (pointerType === 'touch' || !onNavigate) {
          // Touch: pin tooltip (no hover available)
          // No onNavigate: fall back to existing pin behavior
          dispatch({ type: 'click', id });
        } else {
          navigateToRef();
        }
      };
      const onFocus = () => {
        currentAnchor = sup;
        dispatch({ type: 'focus', id });
      };
      const onBlur = () => dispatch({ type: 'blur', id });
      const onKeydown = (e: KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          currentAnchor = sup;
          navigateToRef();
        } else if (e.key === 'Escape') {
          dispatch({ type: 'escape' });
        }
      };

      sup.addEventListener('mouseenter', onMouseenter);
      sup.addEventListener('mouseleave', onMouseleave);
      sup.addEventListener('click', onClick);
      sup.addEventListener('focus', onFocus);
      sup.addEventListener('blur', onBlur);
      sup.addEventListener('keydown', onKeydown);

      cleanups.push(() => {
        sup.removeEventListener('mouseenter', onMouseenter);
        sup.removeEventListener('mouseleave', onMouseleave);
        sup.removeEventListener('click', onClick);
        sup.removeEventListener('focus', onFocus);
        sup.removeEventListener('blur', onBlur);
        sup.removeEventListener('keydown', onKeydown);
      });
    }

    return () => {
      for (const cleanup of cleanups) cleanup();
    };
  });
</script>

{#if tipState.activeId != null && activeCitation && currentAnchor}
  <div
    class="citation-tooltip"
    bind:this={tooltipEl}
    role="tooltip"
    use:floating={{ anchor: currentAnchor, placement: 'top' }}
    onmouseenter={() => dispatch({ type: 'tooltip-mouseenter' })}
    onmouseleave={() => dispatch({ type: 'tooltip-mouseleave' })}
    onfocusin={() => dispatch({ type: 'tooltip-mouseenter' })}
    onfocusout={() => dispatch({ type: 'tooltip-mouseleave' })}
  >
    <div class="source-name">{activeCitation.source_name}</div>
    {#if activeCitation.author || activeCitation.year}
      <div class="meta">
        {[activeCitation.author, activeCitation.year].filter(Boolean).join(', ')}
      </div>
    {/if}
    {#if activeCitation.locator}
      <div class="locator">{activeCitation.locator}</div>
    {/if}
    {#if activeCitation.links.length > 0}
      <div class="links">
        {#each activeCitation.links as link (link.url)}
          <a href={link.url} target="_blank" rel="noopener">{link.label || link.url}</a>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .citation-tooltip {
    z-index: var(--z-tooltip);
    max-width: 320px;
    padding: var(--size-2) var(--size-3);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
    box-shadow: var(--shadow-popover);
    font-size: var(--font-size-1);
    line-height: var(--font-lineheight-3);
    color: var(--color-text);
  }

  .source-name {
    font-weight: 600;
  }

  .meta,
  .locator {
    color: var(--color-text-muted);
  }

  .links {
    margin-top: var(--size-1);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .links a {
    color: var(--color-link);
    text-decoration: none;
    font-size: var(--font-size-0);
  }

  .links a:hover {
    text-decoration: underline;
  }
</style>
