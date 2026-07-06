<!-- @component Test fixture: hosts InlineCitationsPanel over reactive pending
  state and mirrors it as JSON, so tests can assert that panel edits write
  through to the host's entries. -->
<script lang="ts">
  import InlineCitationsPanel from './InlineCitationsPanel.svelte';
  import type { PendingInlineCitation } from '$lib/pending-citations';

  let pending = $state<PendingInlineCitation[]>([
    {
      slug: 'aaaaaaaa',
      sourceId: 1,
      sourceName: 'The Encyclopedia of Pinball',
      sourceType: 'book',
      locator: '',
      quote: '',
    },
  ]);
</script>

<InlineCitationsPanel {pending} text="Kept.[[cite:aaaaaaaa]]" />

<p data-testid="pending-json">{JSON.stringify(pending)}</p>
