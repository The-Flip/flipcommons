<!-- @component Test fixture: hosts CitationInstanceFields over one reactive
  citation with a remove callback and a consumer actions snippet, mirroring the
  citation as JSON so tests can assert edits write through. -->
<script lang="ts">
  import CitationInstanceFields from './CitationInstanceFields.svelte';

  let { withRemove = false }: { withRemove?: boolean } = $props();

  let citation = $state({
    sourceName: 'The Encyclopedia of Pinball',
    sourceType: 'book',
    locator: '',
    quote: '',
  });
  let removed = $state(false);
</script>

<CitationInstanceFields {citation} onremove={withRemove ? () => (removed = true) : undefined}>
  {#snippet actions()}
    <button type="button">Change citation</button>
  {/snippet}
</CitationInstanceFields>

<p data-testid="citation-json">{JSON.stringify(citation)}</p>
<p data-testid="removed">{String(removed)}</p>
