<script lang="ts">
  import type { Snippet } from 'svelte';

  /**
   * Layout-agnostic infinite-scroll sentinel: renders `children` (whatever
   * wrapper the caller provides — a card grid, a row list) followed by a 1px
   * sentinel that calls `onSentinel` when it scrolls into view. The wrapper
   * (`CardGrid`, `<ul>`) lives in the caller, so this owns only the
   * IntersectionObserver and shares it across the card and row list components.
   */
  let {
    hasMore,
    onSentinel,
    children,
  }: {
    hasMore: boolean;
    onSentinel: () => void;
    children: Snippet;
  } = $props();

  let sentinel: HTMLDivElement | undefined = $state();

  $effect(() => {
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          onSentinel();
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  });
</script>

{@render children()}

{#if hasMore}
  <div class="sentinel" bind:this={sentinel}></div>
{/if}

<style>
  .sentinel {
    height: 1px;
  }
</style>
