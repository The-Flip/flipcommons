<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    main,
    sidebar,
  }: {
    main: Snippet;
    sidebar: Snippet;
  } = $props();
</script>

<div class="two-col">
  <div class="main-col">
    {@render main()}
  </div>
  <aside class="sidebar">
    {@render sidebar()}
  </aside>
</div>

<style>
  .two-col {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--size-6);
  }

  @media (--breakpoint-wide) {
    .two-col {
      grid-template-columns: 1fr 18rem;
    }
  }

  .sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
