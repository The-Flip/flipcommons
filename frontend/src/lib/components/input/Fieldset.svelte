<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    legend,
    children,
  }: {
    legend: string;
    children: Snippet;
  } = $props();
</script>

<fieldset class="fieldset">
  <legend>{legend}</legend>
  {@render children()}
</fieldset>

<style>
  .fieldset {
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-3);
    margin: 0;
  }

  legend {
    font-size: var(--font-size-1);
    font-weight: 500;
    color: var(--color-text-muted);
    padding: 0 var(--size-1);
  }
</style>
