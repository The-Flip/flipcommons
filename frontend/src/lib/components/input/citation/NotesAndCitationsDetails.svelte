<!-- @component Collapsible "Notes & Citations" panel for edit forms: the edit
  summary note plus the multi-citation evidence list (EditCitationField). -->
<script lang="ts">
  import EditCitationField from './EditCitationField.svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import type { EditCitationSelection } from '$lib/edit-citation';

  interface Props {
    note?: string;
    citations?: EditCitationSelection[];
    showCitation?: boolean;
    showMixedEditWarning?: boolean;
    noteLabel?: string;
    noteHint?: string;
  }

  let {
    note = $bindable(''),
    citations = $bindable([]),
    showCitation = true,
    showMixedEditWarning = false,
    noteLabel = 'Edit summary',
    noteHint = 'Why are you making this change?',
  }: Props = $props();
</script>

<details class="meta-section">
  <summary>{showCitation ? 'Notes & Citations' : 'Notes'}</summary>
  <div class="meta-fields">
    <TextField label={noteLabel} bind:value={note} hint={noteHint} optional />
    {#if showCitation}
      <EditCitationField bind:citations {showMixedEditWarning} />
    {/if}
  </div>
</details>

<style>
  .meta-section {
    margin-top: var(--size-4);
    border-top: 1px solid var(--color-border-soft);
    padding-top: var(--size-3);
    background: inherit;
  }

  .meta-section > summary {
    cursor: pointer;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    user-select: none;
    background: inherit;
  }

  .meta-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
    margin-top: var(--size-3);
  }
</style>
