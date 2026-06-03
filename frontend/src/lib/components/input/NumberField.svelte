<script lang="ts">
  import FieldGroup from './FieldGroup.svelte';

  let {
    label,
    value = $bindable(''),
    id = '',
    min,
    max,
    step = 1,
    error = '',
  }: {
    label: string;
    value?: string | number;
    id?: string;
    min?: number;
    max?: number;
    step?: number;
    error?: string;
  } = $props();

  let inputEl: HTMLInputElement | undefined = $state();
  let localError = $state('');

  let displayError = $derived(localError || error);

  function validate() {
    if (!inputEl) return;
    if (inputEl.validity.badInput) {
      localError = 'Enter a valid number.';
    } else if (inputEl.validity.rangeUnderflow) {
      localError = `Must be at least ${min}.`;
    } else if (inputEl.validity.rangeOverflow) {
      localError = `Must be at most ${max}.`;
    } else {
      localError = '';
    }
  }
</script>

<FieldGroup {label} {id} error={displayError}>
  {#snippet children(inputId, errorId)}
    <input
      bind:this={inputEl}
      id={inputId}
      type="number"
      {min}
      {max}
      {step}
      bind:value
      oninput={validate}
      onblur={validate}
      aria-invalid={displayError ? true : undefined}
      aria-describedby={displayError ? errorId : undefined}
    />
  {/snippet}
</FieldGroup>
