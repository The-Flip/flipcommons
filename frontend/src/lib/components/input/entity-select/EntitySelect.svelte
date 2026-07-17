<!--
@component
Single-FK typeahead over the entity-autocomplete endpoint, keyed by entity
`type`; binds the chosen `public_id`. Pass `initialSelection` (the saved row)
so the current value renders on mount without a search.
-->
<script lang="ts">
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import EntityCombobox from './EntityCombobox.svelte';

  let {
    type,
    selected = $bindable(null),
    initialSelection = null,
    exclude = [],
    label = '',
    placeholder = 'Search...',
    error = '',
    disabled = false,
    required = false,
    onselect = undefined,
  }: {
    /** Registry key the endpoint searches (`manufacturer`, `title`, …). */
    type: string;
    /** Bound: the chosen `public_id`, or `null` when nothing is selected. */
    selected?: string | null;
    /** Saved row, pre-seeded so the current value renders on mount with no search. */
    initialSelection?: EntityOption | null;
    /** Values to drop from results (e.g. the current record, to forbid self-reference). */
    exclude?: string[];
    label?: string;
    placeholder?: string;
    error?: string;
    disabled?: boolean;
    /** Hide the clear (×) so the field can't be emptied once set. */
    required?: boolean;
    /** Optional: observe the chosen option (label included) on selection. */
    onselect?: (option: EntityOption) => void;
  } = $props();

  const selectedValues = $derived(selected ? [selected] : []);
  const initialOptions = $derived(initialSelection ? [initialSelection] : []);
</script>

<EntityCombobox
  {type}
  {selectedValues}
  {initialOptions}
  {exclude}
  {label}
  {placeholder}
  {error}
  {disabled}
  {required}
  onToggle={(row) => {
    selected = row.value;
    onselect?.(row);
  }}
  onClear={() => (selected = null)}
/>
