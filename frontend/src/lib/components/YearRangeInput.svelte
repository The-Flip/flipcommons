<script lang="ts">
  let {
    min = $bindable<number | null>(null),
    max = $bindable<number | null>(null),
    disabled = false,
  }: {
    min?: number | null;
    max?: number | null;
    /** Disable both inputs (e.g. while the filter sidebar's options stream in). */
    disabled?: boolean;
  } = $props();
</script>

<div class="year-inputs">
  <input
    type="number"
    placeholder="From"
    aria-label="Year from"
    {disabled}
    value={min ?? ''}
    onchange={(e) => {
      const v = e.currentTarget.value;
      min = v ? Number(v) : null;
    }}
  />
  <span class="year-sep">&ndash;</span>
  <input
    type="number"
    placeholder="To"
    aria-label="Year to"
    {disabled}
    value={max ?? ''}
    onchange={(e) => {
      const v = e.currentTarget.value;
      max = v ? Number(v) : null;
    }}
  />
</div>

<style>
  .year-inputs {
    display: flex;
    align-items: center;
    gap: var(--size-2);
  }

  .year-inputs input {
    width: 5.5rem;
    padding: var(--size-2) var(--size-2);
  }

  .year-sep {
    color: var(--color-text-muted);
  }
</style>
