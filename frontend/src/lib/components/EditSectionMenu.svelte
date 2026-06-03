<script lang="ts">
  import ActionMenu from '$lib/components/ui/menu/ActionMenu.svelte';
  import MenuItem from '$lib/components/ui/menu/MenuItem.svelte';
  import type { EditSectionMenuItem } from './edit-section-menu';

  let {
    label = undefined,
    currentKey = undefined,
    disabled = false,
    variant = 'default',
    items,
  }: {
    label?: string;
    currentKey?: string;
    disabled?: boolean;
    variant?: 'default' | 'heading';
    items: EditSectionMenuItem[];
  } = $props();

  let currentLabel = $derived(
    currentKey ? (items.find((item) => item.key === currentKey)?.label ?? 'Edit') : 'Edit',
  );
</script>

<ActionMenu label={label ?? currentLabel} {disabled} {variant}>
  {#each items as item (item.key)}
    {#if item.separatorBefore}
      <hr class="menu-separator" />
    {/if}
    <MenuItem
      href={item.href}
      onclick={item.onclick}
      disabled={item.key === currentKey}
      current={item.key === currentKey}
    >
      {item.label}
    </MenuItem>
  {/each}
</ActionMenu>

<style>
  .menu-separator {
    margin: var(--size-1) 0;
    border: 0;
    border-top: 1px solid var(--color-border-soft);
  }
</style>
