<script lang="ts">
  import FocusContentShell from './FocusContentShell.svelte';

  let {
    backHref = '/titles/medieval-madness',
    recordName = undefined,
    recordHref = undefined,
    maxWidth = undefined,
  }: {
    backHref?: string;
    recordName?: string;
    recordHref?: string;
    maxWidth?: string;
  } = $props();
</script>

{#snippet headingSnippet()}
  <h1>Edit History</h1>
{/snippet}

<FocusContentShell {backHref} {recordName} {recordHref} {maxWidth} heading={headingSnippet}>
  <div>Audit content</div>
</FocusContentShell>
