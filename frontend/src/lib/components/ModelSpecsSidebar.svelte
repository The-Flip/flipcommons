<script lang="ts">
  import { resolve } from '$app/paths';
  import type { ModelDetailSchema } from '$lib/api/schema';

  type Model = ModelDetailSchema;

  let {
    model,
    section = 'all',
    showFranchiseSeries = true,
  }: {
    model: Model;
    section?: 'technology' | 'features' | 'all';
    /** When false, omits Franchise and Series rows — used when those surface as their own sidebar sections. */
    showFranchiseSeries?: boolean;
  } = $props();
</script>

<dl>
  {#if section === 'technology' || section === 'all'}
    {#if model.technology_generation}
      <dt>Generation</dt>
      <dd>
        <a href={resolve(`/technology-generations/${model.technology_generation.public_id}`)}
          >{model.technology_generation.name}</a
        >
      </dd>
    {/if}
    {#if model.technology_subgeneration}
      <dt>Subgeneration</dt>
      <dd>
        <a href={resolve(`/technology-subgenerations/${model.technology_subgeneration.public_id}`)}
          >{model.technology_subgeneration.name}</a
        >
      </dd>
    {/if}
    {#if model.display_type}
      <dt>Display Type</dt>
      <dd>
        <a href={resolve(`/display-types/${model.display_type.public_id}`)}
          >{model.display_type.name}</a
        >
      </dd>
    {/if}
    {#if model.display_subtype}
      <dt>Display</dt>
      <dd>
        <a href={resolve(`/display-subtypes/${model.display_subtype.public_id}`)}
          >{model.display_subtype.name}</a
        >
      </dd>
    {/if}
    {#if model.system}
      <dt>System</dt>
      <dd>
        <a href={resolve(`/systems/${model.system.public_id}`)}>{model.system.name}</a>
      </dd>
    {/if}
  {/if}
  {#if section === 'features' || section === 'all'}
    {#if model.game_format}
      <dt>Format</dt>
      <dd>
        <a href={resolve(`/game-formats/${model.game_format.public_id}`)}
          >{model.game_format.name}</a
        >
      </dd>
    {/if}
    {#if model.cabinet}
      <dt>Cabinet</dt>
      <dd>
        <a href={resolve(`/cabinets/${model.cabinet.public_id}`)}>{model.cabinet.name}</a>
      </dd>
    {/if}
    {#if model.reward_types && model.reward_types.length > 0}
      <dt>Reward Types</dt>
      <dd>
        {#each model.reward_types as rt, i (rt.public_id)}
          {#if i > 0},{/if}
          <a href={resolve(`/reward-types/${rt.public_id}`)}>{rt.name}</a>
        {/each}
      </dd>
    {/if}
    {#if model.themes.length > 0}
      <dt>Themes</dt>
      <dd>
        {#each model.themes as theme, i (theme.public_id)}
          {#if i > 0},{/if}
          <a href={resolve(`/themes/${theme.public_id}`)}>{theme.name}</a>
        {/each}
      </dd>
    {/if}
    {#if model.production_quantity}
      <dt>Units Made</dt>
      <dd>{model.production_quantity}</dd>
    {/if}
    {#if model.player_count}
      <dt>Players</dt>
      <dd>{model.player_count}</dd>
    {/if}
    {#if model.flipper_count}
      <dt>Flippers</dt>
      <dd>{model.flipper_count}</dd>
    {/if}
    {#if model.gameplay_features.length > 0}
      <dt>Features</dt>
      <dd>
        {#each model.gameplay_features as feature, i (feature.public_id)}
          {#if i > 0},{/if}
          <a href={resolve(`/gameplay-features/${feature.public_id}`)}>{feature.name}</a
          >{#if feature.count}&nbsp;({feature.count}){/if}
        {/each}
      </dd>
    {/if}
    {#if showFranchiseSeries && model.franchise}
      <dt>Franchise</dt>
      <dd>
        <a href={resolve(`/franchises/${model.franchise.public_id}`)}>{model.franchise.name}</a>
      </dd>
    {/if}
    {#if showFranchiseSeries && model.series}
      <dt>Series</dt>
      <dd>
        <a href={resolve(`/series/${model.series.public_id}`)}>{model.series.name}</a>
      </dd>
    {/if}
    {#if model.variant_features.length > 0}
      <dt>Variant</dt>
      <dd>{model.variant_features.join(', ')}</dd>
    {/if}
  {/if}
</dl>

<style>
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0 var(--size-3);
    align-items: baseline;
  }

  dt,
  dd {
    font-size: var(--font-size-0);
    margin: 0;
    padding: 2px 0;
  }

  dt {
    color: var(--color-text-muted);
    font-weight: 500;
  }

  dd {
    color: var(--color-text);
  }
</style>
