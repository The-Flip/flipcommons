<!-- @component Harness for the `searchDraft` DOM tests: a search box bound to a draft
over a committed query the test controls by rerendering. -->
<script lang="ts">
  import { searchDraft } from './search-draft.svelte';

  let {
    committed,
    commit,
  }: {
    /** Stands in for the SSR-loaded `q`; rerender to simulate a navigation landing. */
    committed: string;
    commit: (next: string) => void;
  } = $props();

  const draft = searchDraft(
    () => committed,
    (next) => commit(next),
  );
</script>

<input type="search" bind:value={draft.value} />
<button type="button" onclick={() => draft.markCommitted('outside')}>mark committed</button>
