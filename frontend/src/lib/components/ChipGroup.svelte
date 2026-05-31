<script lang="ts">
  let {
    options,
    selected = $bindable(null),
    label = '',
    onchange,
  }: {
    options: { slug: string; label: string; count: number }[];
    selected?: string | null;
    label?: string;
    onchange?: (value: string | null) => void;
  } = $props();
</script>

<div class="chip-group">
  {#if label}
    <span class="filter-label">{label}</span>
  {/if}
  <div class="chips">
    {#each options as opt (opt.slug)}
      <button
        class="chip"
        class:active={selected === opt.slug}
        aria-pressed={selected === opt.slug}
        aria-disabled={opt.count === 0 && selected !== opt.slug}
        disabled={opt.count === 0 && selected !== opt.slug}
        onclick={() => {
          const val = selected === opt.slug ? null : opt.slug;
          selected = val;
          onchange?.(val);
        }}
      >
        {opt.label}
        <span class="chip-count">({opt.count})</span>
      </button>
    {/each}
  </div>
</div>

<style>
  .chip-group {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .filter-label {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-1);
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--size-1);
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    font-family: var(--font-body);
    background-color: var(--color-surface);
    color: var(--color-text);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
    cursor: pointer;
    transition:
      background-color 0.15s var(--ease-2),
      border-color 0.15s var(--ease-2);
  }

  .chip:hover:not(:disabled) {
    border-color: var(--color-link);
  }

  .chip.active {
    background-color: var(--color-link);
    border-color: var(--color-link);
    color: var(--color-text-inverse);
  }

  .chip.active .chip-count {
    color: var(--color-text-inverse-muted);
  }

  .chip:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .chip-count {
    color: var(--color-text-muted);
    font-size: var(--font-size-00, 0.7rem);
  }
</style>
