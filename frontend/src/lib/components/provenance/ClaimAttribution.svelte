<script lang="ts">
  import type { ClaimAttributionSchema } from '$lib/api/schema';
  import ClaimAuthor from './ClaimAuthor.svelte';
  import SmartDate from '$lib/components/SmartDate.svelte';

  let { attribution }: { attribution: ClaimAttributionSchema } = $props();
</script>

<ClaimAuthor {attribution} />
<span aria-hidden="true">·</span>
<SmartDate iso={attribution.created_at} />
