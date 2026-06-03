<script lang="ts">
  import FieldGroup from './FieldGroup.svelte';

  let {
    label,
    value = $bindable(''),
    id = '',
    error = '',
  }: {
    label: string;
    value?: string | number;
    id?: string;
    error?: string;
  } = $props();

  const months = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ];
</script>

<FieldGroup {label} {id} {error}>
  {#snippet children(inputId, errorId)}
    <select
      id={inputId}
      bind:value
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId : undefined}
    >
      <option value="">—</option>
      {#each months as name, i (i)}
        <option value={i + 1}>{name}</option>
      {/each}
    </select>
  {/snippet}
</FieldGroup>

<style>
  select {
    width: 100%;
  }
</style>
