<script lang="ts">
  let {
    attribution = null,
  }: {
    attribution?: {
      requires_attribution?: boolean;
      source_name?: string | null;
      source_url?: string | null;
      license_name?: string | null;
      license_url?: string | null;
      attribution_text?: string | null;
    } | null;
  } = $props();

  const show = $derived(attribution?.requires_attribution && attribution?.source_name);
</script>

{#if show}
  <p class="attribution">
    {#if attribution?.attribution_text}
      {attribution.attribution_text}
    {:else if attribution?.source_url}
      Source: <a href={attribution.source_url} target="_blank" rel="noopener"
        >{attribution.source_name}</a
      >
    {:else}
      Source: {attribution?.source_name}
    {/if}
    {#if attribution?.license_name}
      &middot;
      {#if attribution?.license_url}
        <a href={attribution.license_url} target="_blank" rel="noopener"
          >{attribution.license_name}</a
        >
      {:else}
        {attribution.license_name}
      {/if}
    {/if}
  </p>
{/if}

<style>
  .attribution {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin-top: var(--size-2);
  }

  .attribution a {
    color: var(--color-text-muted);
    text-decoration: underline;
  }
</style>
