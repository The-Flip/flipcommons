<script lang="ts">
  import type { Snippet } from 'svelte';
  import { resolveHref } from '$lib/utils';

  let {
    href,
    children,
    actions,
  }: {
    href?: string;
    children: Snippet;
    actions?: Snippet;
  } = $props();
</script>

<li class="row" class:row--clickable={!!href}>
  {#if href}
    <!--
      Stretched-link pattern: the anchor's ::before pseudo-element fills the
      entire .row via absolute positioning, so clicks anywhere on the row
      that aren't on a button activate the link. No JS — a real anchor
      click. Buttons inside .actions get position: relative; z-index: 1 so
      they sit above the overlay and stay independently clickable.
    -->
    <a href={resolveHref(href)} class="content content--link">{@render children()}</a>
  {:else}
    <div class="content">{@render children()}</div>
  {/if}
  {#if actions}
    <div class="actions">{@render actions()}</div>
  {/if}
</li>

<style>
  .row {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
    padding: var(--size-3) var(--size-4);
    /* surface-muted is the project's "alt rows / panels" token — warmer
       than pure surface, keeps the card from feeling stark on the warm
       page bg in light mode. */
    background: var(--color-surface-muted);
    /* De-emphasized border via half-opacity color-mix so the card edge
       reads as "settled" rather than walled-off. */
    border: 1px solid color-mix(in srgb, var(--color-border-soft) 50%, transparent);
    border-radius: var(--radius-3);
    transition:
      border-color 0.15s ease,
      background-color 0.15s ease;
  }
  .row--clickable {
    cursor: pointer;
  }
  .row--clickable:hover {
    background: var(--color-accent-soft);
    border-color: var(--color-accent-border);
  }
  .content {
    display: flex;
    align-items: baseline;
    gap: var(--size-3);
    min-width: 0;
    color: var(--color-text);
  }
  .content--link {
    text-decoration: none;
  }
  /* Stretched-link overlay: covers the whole .row so clicks on dead space
     (padding, around buttons) navigate via the anchor. */
  .content--link::before {
    content: '';
    position: absolute;
    inset: 0;
  }
  /* Sit actions above the overlay so their buttons remain independently
     clickable without intercepting row-wide navigation. */
  .actions {
    position: relative;
    z-index: 1;
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  @media (--breakpoint-wide) {
    .row {
      flex-direction: row;
      align-items: center;
    }
    .content {
      flex: 1;
    }
    .actions {
      flex-direction: row;
      flex-shrink: 0;
    }
  }
</style>
