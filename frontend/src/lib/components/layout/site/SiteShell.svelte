<script lang="ts">
  import type { Snippet } from 'svelte';
  import Nav from './Nav.svelte';
  import Footer from './Footer.svelte';

  let { children }: { children: Snippet } = $props();
</script>

<Nav />

<main class="page-content">
  {@render children()}
</main>

<Footer />

<style>
  .page-content {
    flex: 1;
    width: 100%;
    max-width: 72rem;
    margin: 0 auto;
    padding: var(--size-6) var(--size-5);
  }
</style>
