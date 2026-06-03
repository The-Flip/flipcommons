<script lang="ts">
  import type { Snippet } from 'svelte';
  import { type EditCitationSelection, buildEditCitationRequest } from '$lib/edit-citation';
  import type { SaveMeta } from '$lib/components/pages/record/edit/editors/entity/model/save-model-claims';
  import Button from '$lib/components/ui/Button.svelte';
  import NotesAndCitationsDetails from '$lib/components/input/citation/NotesAndCitationsDetails.svelte';

  let {
    error = '',
    showCitation = true,
    showMixedEditWarning = false,
    oncancel,
    onsave,
    children,
  }: {
    error?: string;
    showCitation?: boolean;
    showMixedEditWarning?: boolean;
    oncancel: () => void;
    onsave: (meta: SaveMeta) => void;
    children: Snippet;
  } = $props();

  let note = $state('');
  let citation = $state<EditCitationSelection | null>(null);

  export function resetMeta() {
    note = '';
    citation = null;
  }

  function buildMeta(): SaveMeta {
    return {
      note: note || undefined,
      citation: buildEditCitationRequest(citation),
    };
  }
</script>

{#if error}
  <p class="save-error">{error}</p>
{/if}

{@render children()}

<NotesAndCitationsDetails bind:note bind:citation {showCitation} {showMixedEditWarning} />

<div class="form-footer">
  <Button variant="secondary" onclick={oncancel}>Cancel</Button>
  <Button onclick={() => onsave(buildMeta())}>Save</Button>
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
