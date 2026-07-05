<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import FieldGroup from './FieldGroup.svelte';

  let {
    label,
    value = $bindable(''),
    type = 'text',
    id = '',
    placeholder = '',
    optional = false,
    hint = '',
    error = '',
    readonly = false,
    noAutofill = false,
    inputRef = $bindable<HTMLInputElement | undefined>(undefined),
    ...rest
  }: {
    label: string;
    value?: string;
    type?: 'text' | 'url';
    id?: string;
    placeholder?: string;
    optional?: boolean;
    /** Persistent format guidance shown under the label (see FieldGroup). */
    hint?: string;
    error?: string;
    /** Render the input read-only (shown for confirmation, not editing). */
    readonly?: boolean;
    /** Opt the field out of browser autofill and password-manager overlays —
     *  for metadata fields that aren't credentials. */
    noAutofill?: boolean;
    /** Bind to reach the underlying input — e.g. to focus it on mount. */
    inputRef?: HTMLInputElement;
    /** Remaining input attributes (autocomplete, inputmode, data-*, …). */
  } & Omit<HTMLInputAttributes, 'value' | 'type' | 'placeholder' | 'id' | 'readonly'> = $props();

  // The attributes that suppress autofill / password-manager UI, in one place.
  let autofillOff = $derived(
    noAutofill
      ? ({ autocomplete: 'off', 'data-1p-ignore': true, 'data-lpignore': 'true' } as const)
      : {},
  );
</script>

<FieldGroup {label} {id} {optional} {hint} {error}>
  {#snippet children(inputId, describedBy)}
    <input
      {...rest}
      {...autofillOff}
      bind:this={inputRef}
      id={inputId}
      bind:value
      {type}
      {placeholder}
      {readonly}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy}
    />
  {/snippet}
</FieldGroup>

<style>
  /* A read-only field is shown for confirmation, not editing — mute it so it
     doesn't read as an empty editable input. State-specific tweak only. */
  input[readonly] {
    color: var(--color-text-muted);
    cursor: default;
  }
</style>
