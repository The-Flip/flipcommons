<script lang="ts">
  import { tick } from 'svelte';
  import type { Snippet } from 'svelte';
  import { acquireScrollLock } from './scroll-lock';

  type DialogProps = {
    open: boolean;
    onclose: () => void;
    scrim?: 'default' | 'strong';
    ariaDescribedBy?: string;
    initialFocus?: HTMLElement;
    children: Snippet;
  } & (
    | { ariaLabel: string; ariaLabelledBy?: never }
    | { ariaLabelledBy: string; ariaLabel?: never }
  );

  let {
    open,
    onclose,
    scrim = 'default',
    ariaLabel,
    ariaLabelledBy,
    ariaDescribedBy,
    initialFocus,
    children,
  }: DialogProps = $props();

  const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(', ');

  let dialogEl: HTMLDivElement | undefined = $state();

  function getFocusableElements() {
    if (!dialogEl) return [];
    // The aria-hidden filter is load-bearing: .backdrop-dismiss is a <button>
    // and matches FOCUSABLE_SELECTOR, but is aria-hidden + tabindex="-1" so
    // it must stay out of the focus trap and initial-focus fallback.
    return Array.from(dialogEl.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
      (element) =>
        !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true',
    );
  }

  $effect(() => {
    if (!open) return;

    const opener = document.activeElement as HTMLElement | undefined;

    const releaseScrollLock = acquireScrollLock();

    let cancelled = false;
    void tick().then(() => {
      if (cancelled) return;
      if (initialFocus?.isConnected) {
        initialFocus.focus();
        return;
      }
      const [first] = getFocusableElements();
      if (first) first.focus();
      else dialogEl?.focus();
    });

    function handleKeydown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onclose();
        return;
      }

      if (e.key !== 'Tab') return;

      const focusableElements = getFocusableElements();
      if (focusableElements.length === 0) {
        e.preventDefault();
        dialogEl?.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (e.shiftKey && activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      } else if (!e.shiftKey && activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    }

    document.addEventListener('keydown', handleKeydown);

    return () => {
      cancelled = true;
      releaseScrollLock();
      document.removeEventListener('keydown', handleKeydown);
      if (opener?.isConnected) {
        opener.focus();
      }
    };
  });
</script>

{#if open}
  <div
    class="dialog-backdrop"
    role="dialog"
    aria-modal="true"
    aria-label={ariaLabel}
    aria-labelledby={ariaLabelledBy}
    aria-describedby={ariaDescribedBy}
    tabindex="-1"
    bind:this={dialogEl}
    data-scrim={scrim}
  >
    <button
      type="button"
      class="backdrop-dismiss"
      tabindex="-1"
      aria-hidden="true"
      onclick={onclose}
    ></button>
    {@render children()}
  </div>
{/if}

<style>
  .dialog-backdrop {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    background: var(--color-scrim);
  }

  .dialog-backdrop[data-scrim='strong'] {
    background: var(--color-scrim-strong);
  }

  .backdrop-dismiss {
    position: absolute;
    inset: 0;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: pointer;
  }
</style>
