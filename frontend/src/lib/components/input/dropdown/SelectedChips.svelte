<!--
@component
The multi-select chip row: one removable tag per selected value, shown below a
combobox input. Shared by `SearchableSelect` (multi) and `EntityCombobox`
(multi) — each owns its own label source and passes the resolved `{ value,
label }` chips here, so this stays purely presentational.
-->
<script lang="ts">
  let {
    chips,
    disabled = false,
    onremove,
  }: {
    /** One chip per selected value, with its label already resolved by the parent. */
    chips: { value: string; label: string }[];
    disabled?: boolean;
    /** A chip's remove (×) was pressed. */
    onremove: (value: string) => void;
  } = $props();
</script>

{#if chips.length > 0}
  <div class="selected-tags">
    {#each chips as chip (chip.value)}
      <span class="tag">
        {chip.label}
        <button
          class="tag-remove"
          aria-label={`Remove ${chip.label}`}
          {disabled}
          onclick={() => onremove(chip.value)}
        >
          ×
        </button>
      </span>
    {/each}
  </div>
{/if}

<style>
  .selected-tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-1);
    margin-top: var(--size-1);
  }

  .tag {
    display: inline-flex;
    align-items: center;
    gap: var(--size-1);
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    background-color: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
  }

  .tag-remove {
    background: none;
    border: none;
    color: var(--color-text-muted);
    cursor: pointer;
    padding: 0;
    font-size: var(--font-size-1);
    line-height: 1;
  }

  .tag-remove:hover {
    color: var(--color-error-text);
  }
</style>
