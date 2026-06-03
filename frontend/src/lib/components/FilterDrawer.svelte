<script lang="ts">
  import type { Snippet } from 'svelte';
  import FaIcon from '$lib/components/ui/FaIcon.svelte';
  import { faSliders, faXmark } from '@fortawesome/free-solid-svg-icons';

  let {
    label,
    children,
  }: {
    label: string;
    children: Snippet;
  } = $props();

  let open = $state(false);
  let toggleEl: HTMLButtonElement | undefined = $state();
  let drawerEl: HTMLDivElement | undefined = $state();

  function openDrawer() {
    open = true;
  }

  function closeDrawer() {
    open = false;
    toggleEl?.focus();
  }

  $effect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
      const closeBtn = drawerEl?.querySelector<HTMLElement>('.drawer-close');
      closeBtn?.focus();
      return () => {
        document.body.style.overflow = '';
      };
    }
  });

  $effect(() => {
    if (!open) return;
    function handleKeydown(e: KeyboardEvent) {
      if (e.key === 'Escape') closeDrawer();
    }
    document.addEventListener('keydown', handleKeydown);
    return () => document.removeEventListener('keydown', handleKeydown);
  });
</script>

<button class="filter-toggle" bind:this={toggleEl} onclick={openDrawer}>
  <FaIcon icon={faSliders} size="0.9rem" />
  Filters
</button>

{#if open}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="backdrop" onclick={closeDrawer} onkeydown={closeDrawer}></div>
{/if}

<div
  class="drawer"
  class:open
  bind:this={drawerEl}
  role="dialog"
  aria-modal={open}
  aria-label={label}
>
  <div class="drawer-header">
    <button class="drawer-close" onclick={closeDrawer} aria-label="Close filters">
      <FaIcon icon={faXmark} size="1.25rem" />
    </button>
  </div>
  {@render children()}
</div>

<style>
  /* Toggle button — hidden on desktop */
  .filter-toggle {
    display: none;
    align-items: center;
    gap: var(--size-2);
    padding: var(--size-2) var(--size-3);
    font-size: var(--font-size-1);
    font-family: var(--font-body);
    background-color: var(--color-surface);
    color: var(--color-text);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
    cursor: pointer;
  }

  .filter-toggle:hover {
    border-color: var(--color-link);
  }

  /* Drawer header (close button) — hidden on desktop */
  .drawer-header {
    display: none;
  }

  .drawer-close {
    background: none;
    border: none;
    color: var(--color-text-muted);
    cursor: pointer;
    padding: var(--size-1);
  }

  .drawer-close:hover {
    color: var(--color-text);
  }

  /* Backdrop — only visible on mobile */
  .backdrop {
    display: none;
  }

  /* Mobile overrides */
  @media (--breakpoint-narrow) {
    .filter-toggle {
      display: inline-flex;
      margin-bottom: var(--size-3);
    }

    .drawer-header {
      display: flex;
      justify-content: flex-end;
      padding-bottom: var(--size-2);
      border-bottom: 1px solid var(--color-border-soft);
      margin-bottom: var(--size-3);
    }

    .drawer {
      position: fixed;
      top: 0;
      left: 0;
      bottom: 0;
      width: min(20rem, 85vw);
      background-color: var(--color-bg);
      z-index: var(--z-drawer);
      padding: var(--size-4);
      overflow-y: auto;
      transform: translateX(-100%);
      transition: transform 0.25s var(--ease-2);
    }

    .drawer.open {
      transform: translateX(0);
    }

    .backdrop {
      display: block;
      position: fixed;
      inset: 0;
      background-color: var(--color-scrim);
      z-index: var(--z-drawer);
    }
  }
</style>
