<!-- @component Test fixture: hosts EditCitationField over reactive two-citation
  state and mirrors it as JSON, so tests can assert that row edits and removals
  write through to the host's array. -->
<script lang="ts">
  import EditCitationField from './EditCitationField.svelte';
  import type { EditCitationSelection } from '$lib/edit-citation';

  let citations = $state<EditCitationSelection[]>([
    {
      citationSourceId: 7,
      sourceName: 'Williams Flyer',
      sourceType: 'web',
      locator: '',
      quote: '',
    },
    {
      citationSourceId: 9,
      sourceName: 'Pinside thread',
      sourceType: 'web',
      locator: '',
      quote: '',
    },
  ]);
</script>

<EditCitationField bind:citations showMixedEditWarning={true} />

<p data-testid="citations-json">{JSON.stringify(citations)}</p>
