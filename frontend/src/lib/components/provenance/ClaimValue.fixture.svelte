<script lang="ts">
  import type { ClaimValueSchema } from '$lib/api/schema';
  import ClaimValue from './ClaimValue.svelte';

  let { value }: { value: ClaimValueSchema | null | undefined } = $props();
</script>

<ClaimValue {value} />
