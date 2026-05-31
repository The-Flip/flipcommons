<script lang="ts">
  // Placeholder for the filter sidebar while its option lists stream in after
  // the cards (see /titles SSR). Purely presentational; mirrors the sidebar's
  // section rhythm so the layout doesn't jump when the real controls arrive.
  const SECTIONS = Array.from({ length: 8 }, (_, i) => i);
</script>

<aside class="sidebar" aria-hidden="true">
  <div class="bar bar-heading"></div>
  {#each SECTIONS as i (i)}
    <div class="section">
      <div class="bar bar-label"></div>
      <div class="bar bar-control"></div>
    </div>
  {/each}
</aside>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .section {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .bar {
    background-color: var(--color-surface-raised, var(--color-border));
    border-radius: var(--radius-2);
    animation: pulse 1.4s ease-in-out infinite;
  }

  .bar-heading {
    width: 5rem;
    height: var(--font-size-2);
  }

  .bar-label {
    width: 6rem;
    height: var(--font-size-0);
  }

  .bar-control {
    width: 100%;
    height: 2rem;
  }

  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.4;
    }
  }
</style>
