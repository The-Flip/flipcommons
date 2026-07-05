<script lang="ts">
  import type { Snippet } from 'svelte';

  function slugifyLabel(label: string): string {
    return label.toLowerCase().replace(/\s+/g, '-');
  }

  let {
    label,
    id = '',
    optional = false,
    hint = '',
    error = '',
    children,
  }: {
    label: string;
    id?: string;
    optional?: boolean;
    /** Persistent format guidance, rendered under the label and associated
     *  with the input via `aria-describedby`. Use this instead of relying on
     *  placeholder text, which vanishes as soon as the user types. */
    hint?: string;
    error?: string;
    /** Renders the input; receives `(inputId, describedBy)`. `describedBy` is
     *  the space-joined id list for `aria-describedby` (hint and/or error), or
     *  `undefined` when neither is present. */
    children: Snippet<[string, string | undefined]>;
  } = $props();

  const uniqueSuffix = Math.random().toString(36).slice(2, 8);
  let inputId = $derived.by(() => id || `ef-${slugifyLabel(label)}-${uniqueSuffix}`);
  let hintId = $derived(`${inputId}-hint`);
  let errorId = $derived(`${inputId}-error`);
  let describedBy = $derived(
    [hint ? hintId : '', error ? errorId : ''].filter(Boolean).join(' ') || undefined,
  );
</script>

<div class="field-group">
  <label for={inputId}
    >{label}
    {#if optional}<span class="optional">(optional)</span>{/if}</label
  >
  {#if hint}
    <p class="field-hint" id={hintId}>{hint}</p>
  {/if}
  {@render children(inputId, describedBy)}
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

  .field-hint {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0;
  }

  .field-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: 0;
  }
</style>
