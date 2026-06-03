<script lang="ts" module>
  export type ButtonVariant = 'primary' | 'secondary' | 'destructive';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  let {
    children,
    tag = 'button',
    variant = 'primary',
    fullWidth = false,
    ...rest
  }: {
    children: Snippet;
    tag?: string;
    variant?: ButtonVariant;
    fullWidth?: boolean;
    [key: string]: unknown;
  } = $props();
</script>

<svelte:element this={tag} class="btn btn-{variant}" class:btn-full={fullWidth} {...rest}
  >{@render children()}</svelte:element
>

<style>
  .btn {
    display: inline-block;
    padding: var(--size-2) var(--size-4);
    border-radius: var(--radius-2);
    font-size: var(--font-size-1);
    text-decoration: none;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }

  .btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-full {
    display: block;
    width: 100%;
    text-align: center;
  }

  .btn-primary {
    background: var(--color-accent);
    color: var(--color-text-inverse);
    border: none;
  }

  .btn-primary:hover:not(:disabled) {
    opacity: 0.9;
  }

  .btn-secondary {
    background: none;
    border: 1px solid var(--color-border);
    color: var(--color-text-muted);
  }

  .btn-secondary:hover:not(:disabled) {
    /* Subtle neutral tint that reads in both light and dark — 8% of the
       text color over transparent gives a soft fill in either palette. */
    background: color-mix(in srgb, var(--color-text) 8%, transparent);
    color: var(--color-text);
    border-color: var(--color-text-muted);
  }

  .btn-destructive {
    background: var(--color-error-text);
    color: var(--color-text-inverse);
    border: none;
  }

  .btn-destructive:hover:not(:disabled) {
    opacity: 0.9;
  }
</style>
