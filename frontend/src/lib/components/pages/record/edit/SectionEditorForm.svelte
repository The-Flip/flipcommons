<!-- @component Shared edit-form chrome: error line, the section editor body, the Notes & Citations panel and the sticky Cancel/Save footer. -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { type EditCitationSelection, buildEditCitationsRequest } from '$lib/edit-citation';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/entity/model/save-model-claims';
  import Button from '$lib/components/ui/Button.svelte';
  import NotesAndCitationsDetails from '$lib/components/input/citation/NotesAndCitationsDetails.svelte';

  let {
    error = '',
    showCitation = true,
    showMixedEditWarning = false,
    dirty = true,
    oncancel,
    onsave,
    children,
  }: {
    error?: string;
    showCitation?: boolean;
    showMixedEditWarning?: boolean;
    /** Whether the editor has unsaved changes; gates the Save button. Defaults
     *  to true so the form stays saveable when rendered without a dirty owner. */
    dirty?: boolean;
    oncancel: () => void;
    onsave: (meta: SaveMeta) => void;
    children: Snippet;
  } = $props();

  let note = $state('');
  let citations = $state<EditCitationSelection[]>([]);

  export function resetMeta() {
    note = '';
    citations = [];
  }

  function buildMeta(): SaveMeta {
    return {
      note: note || undefined,
      citations: buildEditCitationsRequest(citations),
    };
  }
</script>

{#if error}
  <p class="save-error">{error}</p>
{/if}

{@render children()}

<NotesAndCitationsDetails bind:note bind:citations {showCitation} {showMixedEditWarning} />

<div class="form-footer">
  <Button variant="secondary" onclick={oncancel}>Cancel</Button>
  <Button disabled={!dirty} onclick={() => onsave(buildMeta())}>Save</Button>
</div>

<style>
  .save-error {
    color: var(--color-error-text);
    font-size: var(--font-size-1);
    margin: 0 0 var(--size-3);
  }

  .form-footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--size-3);
    margin-top: var(--size-4);
    position: sticky;
    bottom: calc(-1 * var(--size-4));
    margin-left: calc(-1 * var(--size-4));
    margin-right: calc(-1 * var(--size-4));
    margin-bottom: calc(-1 * var(--size-4));
    padding: var(--size-3) var(--size-4);
    background: var(--color-bg);
    border-top: 1px solid var(--color-border-soft);
  }
</style>
