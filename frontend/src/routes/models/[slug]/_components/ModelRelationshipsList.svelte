<script lang="ts">
  import { resolve } from '$app/paths';
  import type { ModelDetailSchema } from '$lib/api/schema';

  type Model = ModelDetailSchema;

  let { model }: { model: Model } = $props();
</script>

{#if model.title}
  <div class="relationship-group">
    <h3>Parent Title</h3>
    <ul>
      <li><a href={resolve(`/titles/${model.title.public_id}`)}>{model.title.name}</a></li>
    </ul>
  </div>
{/if}

{#if model.variant_of}
  <div class="relationship-group">
    <h3>Parent Model</h3>
    <ul>
      <li>
        <a href={resolve(`/models/${model.variant_of.public_id}`)}>{model.variant_of.name}</a>
        {#if model.variant_of.year}
          <span class="muted">({model.variant_of.year})</span>
        {/if}
      </li>
    </ul>
  </div>
{/if}

{#if model.variants.length > 0}
  <div class="relationship-group">
    <h3>Variants</h3>
    <ul>
      {#each model.variants as variant (variant.public_id)}
        <li>
          <a href={resolve(`/models/${variant.public_id}`)}>{variant.name}</a>
          {#if variant.year}
            <span class="muted">({variant.year})</span>
          {/if}
        </li>
      {/each}
    </ul>
  </div>
{/if}

{#if model.variant_siblings && model.variant_siblings.length > 0}
  <div class="relationship-group">
    <h3>Other Variants</h3>
    <ul>
      {#each model.variant_siblings as sibling (sibling.public_id)}
        <li>
          <a href={resolve(`/models/${sibling.public_id}`)}>{sibling.name}</a>
          {#if sibling.year}
            <span class="muted">({sibling.year})</span>
          {/if}
        </li>
      {/each}
    </ul>
  </div>
{/if}

{#if model.converted_from}
  <div class="relationship-group">
    <h3>Converted From</h3>
    <ul>
      <li>
        <a href={resolve(`/models/${model.converted_from.public_id}`)}
          >{model.converted_from.name}</a
        >
        {#if model.converted_from.year}
          <span class="muted">({model.converted_from.year})</span>
        {/if}
      </li>
    </ul>
  </div>
{/if}

{#if model.conversions && model.conversions.length > 0}
  <div class="relationship-group">
    <h3>Conversions</h3>
    <ul>
      {#each model.conversions as conversion (conversion.public_id)}
        <li>
          <a href={resolve(`/models/${conversion.public_id}`)}>{conversion.name}</a>
          {#if conversion.year}
            <span class="muted">({conversion.year})</span>
          {/if}
        </li>
      {/each}
    </ul>
  </div>
{/if}

{#if model.remake_of}
  <div class="relationship-group">
    <h3>Remake Of</h3>
    <ul>
      <li>
        <a href={resolve(`/models/${model.remake_of.public_id}`)}>{model.remake_of.name}</a>
        {#if model.remake_of.year}
          <span class="muted">({model.remake_of.year})</span>
        {/if}
      </li>
    </ul>
  </div>
{/if}

{#if model.remakes && model.remakes.length > 0}
  <div class="relationship-group">
    <h3>Remakes</h3>
    <ul>
      {#each model.remakes as remake (remake.public_id)}
        <li>
          <a href={resolve(`/models/${remake.public_id}`)}>{remake.name}</a>
          {#if remake.year}
            <span class="muted">({remake.year})</span>
          {/if}
        </li>
      {/each}
    </ul>
  </div>
{/if}

{#if model.bootleg_of}
  <div class="relationship-group">
    <h3>Bootleg Of</h3>
    <ul>
      <li>
        <a href={resolve(`/models/${model.bootleg_of.public_id}`)}>{model.bootleg_of.name}</a>
        {#if model.bootleg_of.year}
          <span class="muted">({model.bootleg_of.year})</span>
        {/if}
      </li>
    </ul>
  </div>
{/if}

{#if model.bootlegs && model.bootlegs.length > 0}
  <div class="relationship-group">
    <h3>Bootlegs</h3>
    <ul>
      {#each model.bootlegs as bootleg (bootleg.public_id)}
        <li>
          <a href={resolve(`/models/${bootleg.public_id}`)}>{bootleg.name}</a>
          {#if bootleg.year}
            <span class="muted">({bootleg.year})</span>
          {/if}
        </li>
      {/each}
    </ul>
  </div>
{/if}

<style>
  .relationship-group {
    margin-bottom: var(--size-3);
  }

  .relationship-group:last-child {
    margin-bottom: 0;
  }

  .relationship-group h3 {
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 0 0 var(--size-1);
  }

  .relationship-group ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .relationship-group li {
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }
</style>
