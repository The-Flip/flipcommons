<script lang="ts">
  import type { ClaimValueSchema } from '$lib/api/schema';
  import ClaimDisplay from './ClaimDisplay.svelte';
  import { formatValue, simplifyClaimValue } from './change-display';

  let { value }: { value: ClaimValueSchema | null | undefined } = $props();

  let raw = $derived(value?.raw);
  let display = $derived(value?.display);
  let simple = $derived(simplifyClaimValue(raw));

  // A relationship-claim dict with exists:false is a negative assertion
  // ("X is *not* the value"). The backend's `display` struct is the same
  // shape for positive and negative assertions; the strike-through —
  // driven by the raw value's `exists` flag — is what disambiguates the
  // two visually.
  let negated = $derived(
    typeof raw === 'object' &&
      raw !== null &&
      !Array.isArray(raw) &&
      (raw as { exists?: unknown }).exists === false,
  );
</script>

{#if display}
  {#if negated}
    <s><ClaimDisplay {display} /></s>
  {:else}
    <ClaimDisplay {display} />
  {/if}
{:else if simple}
  {#if simple.exists}
    {simple.display}
  {:else}
    <s>{simple.display}</s>
  {/if}
{:else}
  {formatValue(raw)}
{/if}
