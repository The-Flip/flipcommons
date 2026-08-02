<script lang="ts">
  // Minimal sidebar standing in for the real Title/Manufacturer sidebars in the
  // FacetedCatalogListing shell test. Exposes its disabled state and the current
  // `filters.foo`/`filters.bar` so the test can observe the shell's rendered
  // state, and buttons that request patches through `onchange` to exercise the
  // intent→URL navigation (two distinct fields, so a test can compose intents).
  type F = { q: string; foo: string | null; bar: string | null };
  type O = { foo: { public_id: string; name: string; count: number }[] };

  let {
    filterOptions,
    disabled = false,
    busy = false,
    filters,
    onchange,
  }: {
    filterOptions: O | undefined;
    disabled?: boolean;
    busy?: boolean;
    filters: F;
    onchange: (patch: Partial<F>) => void;
  } = $props();
</script>

<div aria-busy={busy}>
  <span data-testid="sb-state">{disabled ? 'disabled' : 'enabled'}</span>
  <span data-testid="sb-foo">{filters.foo ?? 'none'}</span>
  <span data-testid="sb-bar">{filters.bar ?? 'none'}</span>
  <span data-testid="sb-options">{filterOptions ? filterOptions.foo.length : 'pending'}</span>
  <button data-testid="sb-set" type="button" {disabled} onclick={() => onchange({ foo: 'bar' })}>
    set foo
  </button>
  <button
    data-testid="sb-set-bar"
    type="button"
    {disabled}
    onclick={() => onchange({ bar: 'baz' })}
  >
    set bar
  </button>
</div>
