<script lang="ts">
  import { streamed } from './streamed.svelte';

  // The test swaps `promise` to simulate a navigation producing a fresh streamed
  // promise; `streamed` reads it inside its `$effect`, so the re-render re-resolves.
  let { promise }: { promise: Promise<string | undefined> } = $props();

  const s = streamed(() => promise);
</script>

<span data-testid="status">{s.status}</span>
<span data-testid="value">{s.value ?? ''}</span>
