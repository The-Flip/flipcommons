<script lang="ts">
  import type { Snippet } from 'svelte';

  function slugifyLabel(label: string): string {
    return label.toLowerCase().replace(/\s+/g, '-');
  }

  let {
    label,
    id = '',
    optional = false,
    error = '',
    children,
  }: {
    label: string;
    id?: string;
    optional?: boolean;
    error?: string;
    children: Snippet<[string, string]>;
  } = $props();

  const uniqueSuffix = Math.random().toString(36).slice(2, 8);
  let inputId = $derived.by(() => id || `ef-${slugifyLabel(label)}-${uniqueSuffix}`);
  let errorId = $derived(`${inputId}-error`);
</script>

<div class="field-group">
  <label for={inputId}
    >{label}
    {#if optional}<span class="optional">(optional)</span>{/if}</label
  >
  {@render children(inputId, errorId)}
  {#if error}
    <p class="field-error" id={errorId} role="alert">{error}</p>
  {/if}
</div>

<style>
  .field-group {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  label {
    font-size: var(--font-size-1);
    font-weight: 500;
    color: var(--color-text-muted);
  }

  .optional {
    font-weight: 400;
    font-size: var(--font-size-0);
  }

  .field-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: 0;
  }
</style>
