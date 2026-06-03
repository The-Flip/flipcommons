<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    heading,
    headingSize = 'var(--font-size-2)',
    open = $bindable(false),
    onEdit = undefined,
    children,
  }: {
    heading: string;
    headingSize?: string;
    open?: boolean;
    onEdit?: () => void;
    children: Snippet;
  } = $props();

  const uid = $props.id();
  const triggerId = `${uid}-trigger`;
  const panelId = `${uid}-panel`;
  const titleId = `${uid}-title`;

  function toggle() {
    open = !open;
  }
</script>

<section class:open>
  <div class="accordion-controls">
    <button
      type="button"
      class="accordion-trigger"
      id={triggerId}
      aria-expanded={open}
      aria-controls={panelId}
      aria-labelledby={titleId}
      onclick={toggle}
    ></button>
    <div class="accordion-header">
      <h2 class="accordion-heading">
        <span id={titleId} class="accordion-title" style:font-size={headingSize}>{heading}</span>
        {#if onEdit && open}
          <button class="edit-link" type="button" onclick={onEdit}>edit</button>
        {/if}
      </h2>
      <svg class="chevron" viewBox="0 0 20 20" aria-hidden="true">
        <path
          d="M6 8l4 4 4-4"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </div>
  </div>
  {#if open}
    <div class="accordion-body" id={panelId} role="region" aria-labelledby={titleId}>
      {@render children()}
    </div>
  {/if}
</section>

<style>
  section {
    border-bottom: 1px solid var(--color-border-soft);
  }

  .accordion-controls {
    position: relative;
    padding: var(--size-3) 0;
  }

  .accordion-trigger {
    position: absolute;
    inset: 0;
    background: none;
    border: none;
    cursor: pointer;
    z-index: 1;
  }

  .accordion-trigger:hover + .accordion-header .accordion-title,
  .accordion-trigger:hover + .accordion-header .chevron {
    color: var(--color-link);
  }

  .accordion-trigger:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
    border-radius: var(--radius-2);
  }

  .accordion-header {
    position: relative;
    z-index: 2;
    display: flex;
    align-items: center;
    gap: var(--size-2);
    pointer-events: none;
  }

  .accordion-heading {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    flex: 1;
    min-width: 0;
    margin: 0;
  }

  .accordion-title {
    font-size: var(--font-size-2);
    font-weight: 600;
    min-width: 0;
    color: var(--color-text);
  }

  .edit-link {
    font-size: var(--font-size-00, 0.75rem);
    font-weight: 400;
    color: var(--color-text-muted);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    flex: 0 0 auto;
    pointer-events: auto;
    position: relative;
    z-index: 3;
  }

  .edit-link::before {
    content: '[';
  }

  .edit-link::after {
    content: ']';
  }

  .edit-link:hover {
    color: var(--color-link);
  }

  .chevron {
    width: 1.25rem;
    height: 1.25rem;
    flex-shrink: 0;
    transition: transform 0.2s ease;
    color: var(--color-text-muted);
    pointer-events: none;
  }

  .open .chevron {
    transform: rotate(180deg);
  }

  .accordion-body {
    padding: 0 0 var(--size-4);
  }
</style>
