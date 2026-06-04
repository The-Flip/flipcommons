<!--
@component
Multi-FK (M2M) typeahead over the entity-autocomplete endpoint, keyed by
entity `type`; binds the selected `public_id`s in order, each shown as a chip.
Pass `initialSelections` (the saved rows) so chips render on mount without a
search.
-->
<script lang="ts">
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import EntityCombobox from './EntityCombobox.svelte';

  let {
    type,
    selected = $bindable([]),
    initialSelections = [],
    exclude = [],
    label = '',
    placeholder = 'Search...',
    error = '',
    disabled = false,
  }: {
    /** Registry key the endpoint searches (`manufacturer`, `title`, …). */
    type: string;
    /** Bound: chosen `public_id`s in selection order, one chip each. */
    selected?: string[];
    /** Saved rows, pre-seeded so existing chips render on mount with no search. */
    initialSelections?: EntityOption[];
    /** Values to drop from results (e.g. the current record, to forbid self-reference). */
    exclude?: string[];
    label?: string;
    placeholder?: string;
    error?: string;
    disabled?: boolean;
  } = $props();

  function toggle(value: string) {
    selected = selected.includes(value)
      ? selected.filter((v) => v !== value)
      : [...selected, value];
  }
</script>

<EntityCombobox
  {type}
  multi
  selectedValues={selected}
  initialOptions={initialSelections}
  {exclude}
  {label}
  {placeholder}
  {error}
  {disabled}
  onToggle={(row) => toggle(row.value)}
  onRemove={(value) => (selected = selected.filter((v) => v !== value))}
/>
