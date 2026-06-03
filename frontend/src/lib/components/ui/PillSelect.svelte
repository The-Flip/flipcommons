<script lang="ts" generics="T extends string">
  import ActionMenu from '$lib/components/ui/menu/ActionMenu.svelte';
  import MenuItem from '$lib/components/ui/menu/MenuItem.svelte';

  type Option = { value: T; label: string };

  let {
    value,
    options,
    purpose,
    placeholder = '—',
    emptyValueLabel = 'none',
    disabled = false,
    onchange,
  }: {
    value: T | null | undefined;
    options: Option[];
    /**
     * Describes what is being selected, e.g. "Image category". Combined with the
     * current value to form the trigger's accessible name (e.g. "Image category: playfield").
     */
    purpose: string;
    placeholder?: string;
    emptyValueLabel?: string;
    disabled?: boolean;
    onchange: (value: T) => void;
  } = $props();

  const currentLabel = $derived(options.find((o) => o.value === value)?.label ?? placeholder);
  const accessibleName = $derived(`${purpose}: ${value == null ? emptyValueLabel : currentLabel}`);

  function handleSelect(next: T) {
    if (next === value) return;
    onchange(next);
  }
</script>

<ActionMenu variant="pill" label={currentLabel} ariaLabel={accessibleName} {disabled}>
  {#each options as opt (opt.value)}
    <MenuItem current={opt.value === value} onclick={() => handleSelect(opt.value)}>
      {opt.label}
    </MenuItem>
  {/each}
</ActionMenu>
