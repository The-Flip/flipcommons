<script lang="ts">
  import ActionMenu from './ActionMenu.svelte';
  import MenuItem from './MenuItem.svelte';

  let {
    selected = $bindable<string>('playfield'),
    onselect,
  }: {
    selected?: string;
    onselect?: (value: string) => void;
  } = $props();

  const options = ['playfield', 'backglass', 'cabinet'];

  function pick(value: string) {
    selected = value;
    onselect?.(value);
  }
</script>

<ActionMenu variant="pill" label={selected} ariaLabel={`Image category: ${selected}`}>
  {#each options as opt (opt)}
    <MenuItem current={opt === selected} onclick={() => pick(opt)}>{opt}</MenuItem>
  {/each}
</ActionMenu>
