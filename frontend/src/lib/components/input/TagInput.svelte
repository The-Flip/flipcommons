<script lang="ts">
  import FieldGroup from './FieldGroup.svelte';

  let {
    label,
    tags = $bindable([]),
    placeholder = '',
    optional = false,
    error = '',
  }: {
    label: string;
    tags?: string[];
    placeholder?: string;
    optional?: boolean;
    error?: string;
  } = $props();

  let inputValue = $state('');

  function addTag(raw: string) {
    const val = raw.trim();
    if (!val) return;
    // Case-insensitive duplicate check
    if (tags.some((t) => t.toLowerCase() === val.toLowerCase())) return;
    tags = [...tags, val];
    inputValue = '';
  }

  function removeTag(index: number) {
    tags = tags.filter((_, i) => i !== index);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(inputValue);
    }
    // Backspace on empty input removes last tag
    if (e.key === 'Backspace' && inputValue === '' && tags.length > 0) {
      tags = tags.slice(0, -1);
    }
  }

  function handlePaste(e: ClipboardEvent) {
    const text = e.clipboardData?.getData('text') ?? '';
    if (text.includes(',')) {
      e.preventDefault();
      for (const part of text.split(',')) {
        addTag(part);
      }
    }
  }
</script>

<FieldGroup {label} {optional} {error}>
  {#snippet children(inputId, errorId)}
    <input
      id={inputId}
      type="text"
      bind:value={inputValue}
      {placeholder}
      onkeydown={handleKeydown}
      onpaste={handlePaste}
      onblur={() => addTag(inputValue)}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId : undefined}
    />
    {#if tags.length > 0}
      <div class="selected-tags">
        {#each tags as tag, i (i)}
          <span class="tag">
            {tag}
            <button class="tag-remove" aria-label={`Remove ${tag}`} onclick={() => removeTag(i)}>
              &times;
            </button>
          </span>
        {/each}
      </div>
    {/if}
  {/snippet}
</FieldGroup>

<style>
  .selected-tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-1);
    margin-top: var(--size-1);
  }

  .tag {
    display: inline-flex;
    align-items: center;
    gap: var(--size-1);
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    background-color: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
  }

  .tag-remove {
    background: none;
    border: none;
    color: var(--color-text-muted);
    cursor: pointer;
    padding: 0;
    font-size: var(--font-size-1);
    line-height: 1;
  }

  .tag-remove:hover {
    color: var(--color-error-text);
  }
</style>
