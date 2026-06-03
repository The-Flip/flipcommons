<script lang="ts">
  import FieldGroup from './FieldGroup.svelte';

  let {
    label,
    value = $bindable(''),
    type = 'text',
    id = '',
    placeholder = '',
    optional = false,
    error = '',
  }: {
    label: string;
    value?: string;
    type?: 'text' | 'url';
    id?: string;
    placeholder?: string;
    optional?: boolean;
    error?: string;
  } = $props();
</script>

<FieldGroup {label} {id} {optional} {error}>
  {#snippet children(inputId, errorId)}
    <input
      id={inputId}
      bind:value
      {type}
      {placeholder}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId : undefined}
    />
  {/snippet}
</FieldGroup>
