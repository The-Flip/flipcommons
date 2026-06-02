<script lang="ts">
  // Minimal bindable sidebar standing in for the real Title/Manufacturer sidebars
  // in the FacetedCatalogListing shell test. Exposes its disabled state and the
  // current `filters.foo` so the test can observe the shell's filter loop, and a
  // button that mutates `filters` to exercise the filters→URL navigation.
  type F = { query: string; foo: string | null };
  type O = { foo: { public_id: string; name: string; count: number }[] };

  let {
    filterOptions,
    disabled = false,
    busy = false,
    filters = $bindable(),
  }: {
    filterOptions: O | undefined;
    disabled?: boolean;
    busy?: boolean;
    filters: F;
  } = $props();
</script>

<div aria-busy={busy}>
  <span data-testid="sb-state">{disabled ? 'disabled' : 'enabled'}</span>
  <span data-testid="sb-foo">{filters.foo ?? 'none'}</span>
  <span data-testid="sb-options">{filterOptions ? filterOptions.foo.length : 'pending'}</span>
  <button data-testid="sb-set" type="button" {disabled} onclick={() => (filters.foo = 'bar')}>
    set foo
  </button>
</div>
