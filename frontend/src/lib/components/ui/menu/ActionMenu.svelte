<script lang="ts">
  import { setContext, untrack, type Snippet } from 'svelte';

  import { floating } from '$lib/actions/floating';

  type Props = {
    label: string;
    disabled?: boolean;
    variant?: 'default' | 'heading' | 'pill' | 'bare';
    role?: 'menu' | 'listbox';
    ariaLabel?: string;
    trigger?: Snippet;
    children: Snippet;
  };

  let {
    label,
    disabled = false,
    variant = 'default',
    role: roleProp,
    ariaLabel,
    trigger,
    children,
  }: Props = $props();

  const role: 'menu' | 'listbox' = $derived(roleProp ?? (variant === 'pill' ? 'listbox' : 'menu'));
  const placement = $derived(
    variant === 'pill' ? 'top-start' : variant === 'heading' ? 'bottom-start' : 'bottom-end',
  );
  // Context captures the role at construction time and is read once by descendants;
  // role is stable for the lifetime of the component for all current call sites.
  setContext<'menu' | 'listbox'>(
    'action-menu-role',
    untrack(() => role),
  );

  let open = $state(false);
  let triggerEl: HTMLButtonElement | undefined = $state();
  let menuEl: HTMLDivElement | undefined = $state();
  let pendingFocusTarget: 'first' | 'last' | null = $state(null);
  const uid = $props.id();
  const menuId = `${uid}-menu`;

  function getMenuItems() {
    return Array.from(
      menuEl?.querySelectorAll<HTMLElement>('[role="menuitem"], [role="option"]') ?? [],
    );
  }

  function focusMenuItem(index: number) {
    const items = getMenuItems();
    if (items.length === 0) return;

    const normalizedIndex = ((index % items.length) + items.length) % items.length;

    for (const [itemIndex, item] of items.entries()) {
      item.tabIndex = itemIndex === normalizedIndex ? 0 : -1;
    }

    items[normalizedIndex].focus();
  }

  function openMenu({ focus }: { focus?: 'first' | 'last' } = {}) {
    if (disabled) return;
    pendingFocusTarget = focus ?? null;
    open = true;
  }

  function closeMenu({ restoreFocus = false }: { restoreFocus?: boolean } = {}) {
    open = false;
    if (restoreFocus) triggerEl?.focus();
  }

  function toggleMenu() {
    if (disabled) return;
    if (open) {
      closeMenu();
      return;
    }

    openMenu();
  }

  function handleTriggerKeydown(event: KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!open) openMenu({ focus: 'first' });
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) openMenu({ focus: 'last' });
      return;
    }

    if ((event.key === 'Enter' || event.key === ' ') && !open) {
      event.preventDefault();
      openMenu({ focus: 'first' });
      return;
    }

    if (event.key === 'Escape' && open) {
      event.preventDefault();
      closeMenu({ restoreFocus: true });
    }
  }

  function handleMenuKeydown(event: KeyboardEvent) {
    const items = getMenuItems();
    if (items.length === 0) return;

    const currentIndex = items.findIndex((item) => item === document.activeElement);

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        focusMenuItem(currentIndex < 0 ? 0 : currentIndex + 1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        focusMenuItem(currentIndex < 0 ? items.length - 1 : currentIndex - 1);
        break;
      case 'Home':
        event.preventDefault();
        focusMenuItem(0);
        break;
      case 'End':
        event.preventDefault();
        focusMenuItem(items.length - 1);
        break;
      case 'Escape':
        event.preventDefault();
        closeMenu({ restoreFocus: true });
        break;
      case 'Tab':
        closeMenu();
        break;
    }
  }

  function handleMenuClick(event: MouseEvent) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest('[role="menuitem"], [role="option"]')) {
      // For listbox semantics restore focus to trigger after selection (matches
      // native <select> and ARIA Authoring Practices). Action menus typically
      // hand focus off to whatever the action opens, so keep the existing
      // behavior there.
      closeMenu({ restoreFocus: role === 'listbox' });
    }
  }

  $effect(() => {
    if (disabled && open) {
      closeMenu();
    }
  });

  $effect(() => {
    if (!open || pendingFocusTarget == null) return;

    const items = getMenuItems();
    for (const item of items) item.tabIndex = -1;

    if (pendingFocusTarget === 'last') {
      focusMenuItem(items.length - 1);
    } else {
      focusMenuItem(0);
    }

    pendingFocusTarget = null;
  });

  $effect(() => {
    if (!open) return;

    function isInsideMenu(target: EventTarget | null) {
      return target instanceof Node && (triggerEl?.contains(target) || menuEl?.contains(target));
    }

    function handleKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeMenu({ restoreFocus: true });
      }
    }

    function handlePointerDown(event: PointerEvent) {
      if (isInsideMenu(event.target)) return;
      closeMenu();
    }

    function handleFocusIn(event: FocusEvent) {
      if (isInsideMenu(event.target)) return;
      closeMenu();
    }

    document.addEventListener('keydown', handleKeydown);
    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('focusin', handleFocusIn);

    return () => {
      document.removeEventListener('keydown', handleKeydown);
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('focusin', handleFocusIn);
    };
  });

  // Close if the trigger is hidden out from under us (e.g. a responsive
  // breakpoint swaps which trigger is rendered). The menu is portaled to
  // <body>, so it would otherwise stay visible and get repositioned against
  // a zero-sized anchor.
  $effect(() => {
    if (!open || !triggerEl) return;

    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect && rect.width === 0 && rect.height === 0) closeMenu();
    });
    observer.observe(triggerEl);

    return () => observer.disconnect();
  });
</script>

<button
  bind:this={triggerEl}
  type="button"
  class="trigger"
  class:heading={variant === 'heading'}
  class:pill={variant === 'pill'}
  class:bare={variant === 'bare'}
  {disabled}
  aria-haspopup={role === 'listbox' ? 'listbox' : 'menu'}
  aria-expanded={open}
  aria-controls={open ? menuId : undefined}
  aria-label={ariaLabel ?? (trigger ? label : undefined)}
  onclick={toggleMenu}
  onkeydown={handleTriggerKeydown}
>
  {#if trigger}{@render trigger()}{:else}{label}{/if}
</button>
{#if open && triggerEl}
  <div
    bind:this={menuEl}
    id={menuId}
    class="menu"
    {role}
    tabindex="-1"
    aria-label={ariaLabel ?? label}
    data-placement={placement}
    use:floating={{ anchor: triggerEl, placement }}
    onkeydown={handleMenuKeydown}
    onclick={handleMenuClick}
  >
    {@render children()}
  </div>
{/if}

<style>
  .trigger {
    color: var(--color-text-muted);
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    font-size: var(--font-size-0);
    font-family: inherit;
  }

  .trigger:not(.bare)::after {
    content: ' \25BE';
    font-size: 0.75em;
  }

  .trigger.bare {
    color: inherit;
    font-size: inherit;
    line-height: 0;
    display: inline-flex;
    align-items: center;
  }

  .trigger.heading {
    font-size: inherit;
    font-weight: inherit;
    color: inherit;
  }

  .trigger.pill {
    background: var(--color-scrim);
    color: var(--color-text-inverse);
    font-size: var(--font-size-0);
    padding: 0.1em 0.4em;
    border-radius: var(--radius-1);
  }

  .trigger.pill:hover,
  .trigger.pill[aria-expanded='true'] {
    background: var(--color-scrim-strong);
    color: var(--color-text-inverse);
  }

  .trigger:hover,
  .trigger[aria-expanded='true'] {
    color: var(--color-link);
  }

  /* Bare variant defers fully to its parent's color, including on hover —
     the parent decides idle and hover colors via inheritance. */
  .trigger.bare:hover,
  .trigger.bare[aria-expanded='true'] {
    color: inherit;
  }

  .trigger:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .trigger:disabled::after {
    opacity: 0.75;
  }

  .trigger:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }

  .menu {
    background: var(--color-bg);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-1) 0;
    min-width: 7rem;
    z-index: var(--z-dropdown);
    box-shadow: var(--shadow-popover);
  }
</style>
