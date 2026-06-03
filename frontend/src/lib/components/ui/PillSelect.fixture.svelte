<script lang="ts">
  import PillSelect from './PillSelect.svelte';

  let {
    value = $bindable<string | null>('playfield'),
    options = [
      { value: 'playfield', label: 'playfield' },
      { value: 'backglass', label: 'backglass' },
      { value: 'cabinet', label: 'cabinet' },
    ],
    purpose = 'Image category',
    disabled = false,
    onchange,
  }: {
    value?: string | null;
    options?: { value: string; label: string }[];
    purpose?: string;
    disabled?: boolean;
    onchange?: (value: string) => void;
  } = $props();

  function handleChange(next: string) {
    value = next;
    onchange?.(next);
  }
</script>

<PillSelect {value} {options} {purpose} {disabled} onchange={handleChange} />
