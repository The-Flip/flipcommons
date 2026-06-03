<script lang="ts">
  let {
    label,
    onRemove,
  }: {
    /** Human-readable text shown in the chip. */
    label: string;
    /** Called when the user clicks the chip's remove button. */
    onRemove: () => void;
  } = $props();
</script>

<span class="filter-chip" role="listitem">
  {label}
  <button class="chip-remove" aria-label="Remove filter: {label}" onclick={onRemove}>
    &times;
  </button>
</span>

<style>
  .filter-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--size-1);
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    background-color: var(--color-accent);
    color: var(--color-text-inverse);
    border-radius: var(--radius-2);
  }

  .chip-remove {
    background: none;
    border: none;
    color: var(--color-text-inverse-muted);
    cursor: pointer;
    padding: 0;
    font-size: var(--font-size-1);
    line-height: 1;
  }

  .chip-remove:hover {
    color: var(--color-text-inverse);
  }
</style>
