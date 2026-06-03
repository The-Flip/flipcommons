<script lang="ts">
  import { getContext, type Snippet } from 'svelte';

  let {
    href = undefined,
    onclick = undefined,
    disabled = false,
    current = false,
    reload = false,
    children,
  }: {
    href?: string;
    onclick?: () => void;
    disabled?: boolean;
    current?: boolean;
    /** Force a full-page navigation. Only meaningful when `href` is set —
     *  ignored for button-style items. Set for non-SvelteKit routes
     *  (e.g. Django views). */
    reload?: boolean;
    children: Snippet;
  } = $props();

  const parentRole = getContext<'menu' | 'listbox'>('action-menu-role') ?? 'menu';
  const itemRole = parentRole === 'listbox' ? 'option' : 'menuitem';
  const ariaSelected = $derived(parentRole === 'listbox' ? current : undefined);
</script>

{#if disabled}
  <span
    class:current
    class="menu-item disabled"
    role={itemRole}
    aria-disabled="true"
    aria-selected={ariaSelected}
    tabindex="-1"
  >
    {@render children()}
  </span>
{:else if href}
  <a
    class:current
    class="menu-item"
    {href}
    role={itemRole}
    aria-selected={ariaSelected}
    tabindex="-1"
    data-sveltekit-reload={reload ? '' : undefined}
  >
    {@render children()}
  </a>
{:else}
  <button
    class:current
    class="menu-item"
    type="button"
    role={itemRole}
    aria-selected={ariaSelected}
    tabindex="-1"
    {onclick}
  >
    {@render children()}
  </button>
{/if}

<style>
  /* Parents may override --menu-item-font-size and --menu-item-padding via
     inheritance to retune density. Defaults are sized for compact in-page
     menus; the site nav scales them up. */
  .menu-item {
    display: block;
    width: 100%;
    padding: var(--menu-item-padding, var(--size-1) var(--size-3));
    font-size: var(--menu-item-font-size, var(--font-size-0));
    font-family: inherit;
    color: var(--color-text);
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    text-align: start;
    white-space: nowrap;
  }

  /* Hover/focus uses an ink-tinted overlay in light mode (pure white on
     warm-cream looked harsh). Dark mode keeps the existing flat surface. */
  .menu-item:hover,
  .menu-item:focus-visible {
    background: color-mix(in srgb, var(--color-text) 10%, transparent);
    color: var(--color-link);
  }

  @media (prefers-color-scheme: dark) {
    .menu-item:hover,
    .menu-item:focus-visible {
      background: var(--color-surface);
    }
  }

  .menu-item.current {
    font-weight: 600;
  }

  /* Menus: "you are here" gets a tinted background that adapts to both
     themes (ink on warm-cream in light mode, light gray on near-black in
     dark mode). On hover/focus, deepen the tint so the item visibly
     reacts even though it's already highlighted. */
  .menu-item.current[role='menuitem'] {
    background: color-mix(in srgb, var(--color-text) 10%, transparent);
  }

  .menu-item.current[role='menuitem']:hover,
  .menu-item.current[role='menuitem']:focus-visible {
    background: color-mix(in srgb, var(--color-text) 18%, transparent);
  }

  /* Listboxes: the selected option gets a checkmark, like a native <select>. */
  .menu-item.current[role='option']::before {
    content: '✓ ';
  }

  .menu-item.disabled {
    cursor: default;
    color: var(--color-text-muted);
  }

  .menu-item.disabled:hover {
    background: none;
    color: var(--color-text-muted);
  }

  .menu-item:focus-visible {
    outline: none;
  }
</style>
