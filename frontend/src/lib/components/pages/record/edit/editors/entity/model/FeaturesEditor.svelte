<script lang="ts">
  import { untrack } from 'svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import EntityMultiSelect from '$lib/components/input/entity-select/EntityMultiSelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import Fieldset from '$lib/components/input/Fieldset.svelte';
  import NumberField from '$lib/components/input/NumberField.svelte';
  import { diffScalarFields, publicIdSetChanged } from '$lib/edit-helpers';
  import { fetchFieldConstraints, fc, type FieldConstraints } from '$lib/field-constraints';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import {
    EMPTY_EDIT_OPTIONS,
    fetchModelEditOptions,
    toSelectOptions,
    type ModelEditOptions,
  } from './model-edit-options';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  type GameplayFeatureRef = { public_id: string; name?: string; count?: number | null };
  // themes ship as EntityRef ({ name, public_id }); name seeds the chip labels.
  type ThemeRef = { public_id: string; name: string };

  type FeaturesModel = {
    cabinet?: { public_id: string } | null;
    reward_types: { public_id: string }[];
    tags: { public_id: string }[];
    themes: ThemeRef[];
    production_quantity: string;
    player_count?: number | null;
    flipper_count?: number | null;
    gameplay_features: GameplayFeatureRef[];
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<FeaturesModel> = $props();

  type FeaturesFormFields = {
    cabinet: string;
    production_quantity: string | number;
    player_count: string | number;
    flipper_count: string | number;
  };

  function extractFields(m: FeaturesModel): FeaturesFormFields {
    return {
      cabinet: m.cabinet?.public_id ?? '',
      production_quantity: m.production_quantity ?? '',
      player_count: m.player_count ?? '',
      flipper_count: m.flipper_count ?? '',
    };
  }

  // untrack: intentional one-time capture; component re-mounts when modal reopens
  const original = untrack(() => extractFields(initialData));
  let fields = $state<FeaturesFormFields>({ ...original });

  // Simple M2M fields — stored as slug arrays
  const originalThemes = untrack(() => initialData.themes);
  const originalTags = untrack(() => initialData.tags);
  const originalRewardTypes = untrack(() => initialData.reward_types);

  let themes = $state<string[]>(untrack(() => initialData.themes.map((t) => t.public_id)));
  // Seed theme chips so they render on mount with no search.
  const initialThemes: EntityOption[] = untrack(() =>
    initialData.themes.map((t) => ({ value: t.public_id, label: t.name })),
  );
  let tags = $state<string[]>(untrack(() => initialData.tags.map((t) => t.public_id)));
  let rewardTypes = $state<string[]>(
    untrack(() => initialData.reward_types.map((t) => t.public_id)),
  );

  // Gameplay features — slug + optional count. `initial` is the row's saved
  // feature, frozen at creation, so the typeahead renders it on mount without a
  // search; it must NOT track the live `slug` (see PeopleEditor for why).
  type KeyedFeature = {
    key: number;
    // Typed `string` (not `string | null`) because it *is* the save-payload
    // field; the truthy filter in save() drops rows the widget cleared to null.
    // (Per-row payload fields stay `string`; single top-level FKs use `string | null`.)
    slug: string;
    count: string | number;
    initial: EntityOption | null;
  };
  let keyCounter = 0;

  function toKeyed(features: GameplayFeatureRef[]): KeyedFeature[] {
    return features.map((f) => ({
      key: keyCounter++,
      slug: f.public_id,
      count: f.count ?? '',
      initial: { value: f.public_id, label: f.name ?? f.public_id },
    }));
  }

  const originalFeatures = untrack(() => initialData.gameplay_features);
  let features = $state<KeyedFeature[]>(untrack(() => toKeyed(initialData.gameplay_features)));

  let fieldErrors = $state<FieldErrors>({});
  let editOptions = $state<ModelEditOptions>(EMPTY_EDIT_OPTIONS);
  let constraints = $state<FieldConstraints>({});

  $effect(() => {
    fetchFieldConstraints('model').then((c) => {
      constraints = c;
    });
  });

  $effect(() => {
    fetchModelEditOptions().then((opts) => {
      editOptions = opts;
    });
  });

  function addFeature() {
    features = [...features, { key: keyCounter++, slug: '', count: '', initial: null }];
  }

  function removeFeature(index: number) {
    features = features.filter((_, i) => i !== index);
  }

  function featuresChanged(): boolean {
    const clean = features
      .filter((f) => f.slug)
      .map((f) => `${f.slug}:${f.count}`)
      .sort();
    const orig = originalFeatures.map((f) => `${f.public_id}:${f.count ?? ''}`).sort();
    return JSON.stringify(clean) !== JSON.stringify(orig);
  }

  let dirty = $derived.by(
    () =>
      Object.keys(diffScalarFields(fields, original)).length > 0 ||
      publicIdSetChanged(themes, originalThemes) ||
      publicIdSetChanged(tags, originalTags) ||
      publicIdSetChanged(rewardTypes, originalRewardTypes) ||
      featuresChanged(),
  );

  $effect(() => {
    ondirtychange(dirty);
  });

  export function isDirty(): boolean {
    return dirty;
  }

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};

    // Reject incomplete feature rows (count without a feature selected)
    const incompleteFeatures = features.filter((f) => !f.slug && f.count !== '');
    if (incompleteFeatures.length > 0) {
      for (const row of incompleteFeatures) {
        fieldErrors[`gameplay_features.${row.slug}`] = 'Select a feature or remove this row.';
      }
      onerror('Please fix the errors below.');
      return;
    }

    const changed = diffScalarFields(fields, original);
    const themesChanged = publicIdSetChanged(themes, originalThemes);
    const tagsChanged = publicIdSetChanged(tags, originalTags);
    const rewardTypesChanged = publicIdSetChanged(rewardTypes, originalRewardTypes);
    const gfChanged = featuresChanged();

    if (!dirty) {
      onsaved();
      return;
    }

    const result: SaveResult = await saveModelClaims(slug, {
      fields: Object.keys(changed).length > 0 ? changed : undefined,
      themes: themesChanged ? themes : undefined,
      tags: tagsChanged ? tags : undefined,
      reward_types: rewardTypesChanged ? rewardTypes : undefined,
      gameplay_features: gfChanged
        ? features
            .filter((f) => f.slug)
            .map((f) => ({
              slug: f.slug,
              count: f.count === '' ? null : Number(f.count),
            }))
        : undefined,
      ...meta,
    });

    if (result.ok) {
      onsaved();
    } else {
      fieldErrors = result.fieldErrors;
      onerror(
        Object.keys(result.fieldErrors).length > 0 ? 'Please fix the errors below.' : result.error,
      );
    }
  }
</script>

<div class="features-editor">
  <div class="features-grid">
    <SearchableSelect
      label="Cabinet"
      options={toSelectOptions(editOptions.cabinets ?? [])}
      bind:selected={fields.cabinet}
      error={fieldErrors.cabinet ?? ''}
      allowZeroCount
      showCounts={false}
      placeholder="Search cabinets..."
    />
    <SearchableSelect
      label="Reward types"
      options={toSelectOptions(editOptions.reward_types ?? [])}
      bind:selected={rewardTypes}
      multi
      allowZeroCount
      showCounts={false}
      placeholder="Search reward types..."
    />
    <SearchableSelect
      label="Tags"
      options={toSelectOptions(editOptions.tags ?? [])}
      bind:selected={tags}
      multi
      allowZeroCount
      showCounts={false}
      placeholder="Search tags..."
    />
    <EntityMultiSelect
      type="theme"
      label="Themes"
      bind:selected={themes}
      initialSelections={initialThemes}
      placeholder="Search themes..."
    />
    <NumberField
      label="Players"
      bind:value={fields.player_count}
      error={fieldErrors.player_count ?? ''}
      {...fc(constraints, 'player_count')}
    />
    <NumberField
      label="Flippers"
      bind:value={fields.flipper_count}
      error={fieldErrors.flipper_count ?? ''}
      {...fc(constraints, 'flipper_count')}
    />
    <NumberField
      label="Production quantity"
      bind:value={fields.production_quantity}
      error={fieldErrors.production_quantity ?? ''}
      min={0}
    />
  </div>

  <Fieldset legend="Gameplay Features">
    <div class="gf-list">
      {#each features as feature, i (feature.key)}
        {@const rowError = fieldErrors[`gameplay_features.${feature.slug}`] ?? ''}
        <div class="gf-row">
          <div class="gf-select">
            <EntitySelect
              type="gameplay-feature"
              label=""
              bind:selected={features[i].slug}
              initialSelection={feature.initial}
              placeholder="Search features..."
            />
          </div>
          <div class="gf-count">
            <NumberField label="" bind:value={features[i].count} min={1} />
          </div>
          <button type="button" class="remove-btn" onclick={() => removeFeature(i)}>&times;</button>
        </div>
        {#if rowError}
          <p class="row-error" role="alert">{rowError}</p>
        {/if}
      {/each}
      <button
        type="button"
        class="add-btn"
        disabled={features.some((f) => !f.slug)}
        onclick={addFeature}
      >
        Add feature
      </button>
    </div>
  </Fieldset>
</div>

<style>
  .features-editor {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .features-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }

  .row-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: 0;
  }

  .gf-list {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .gf-row {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: var(--size-2);
    align-items: end;
  }

  .gf-count {
    width: 5rem;
  }

  .remove-btn {
    background: none;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-1);
    padding: 0.4rem 0.6rem;
    cursor: pointer;
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    line-height: 1;
  }

  .remove-btn:hover {
    color: var(--color-error-text);
    border-color: var(--color-error-text);
  }

  .add-btn {
    background: none;
    border: 1px dashed var(--color-border-soft);
    border-radius: var(--radius-1);
    padding: var(--size-2) var(--size-3);
    cursor: pointer;
    color: var(--color-text-muted);
    width: 100%;
  }

  .add-btn:hover:not(:disabled) {
    border-color: var(--color-text-muted);
  }

  .add-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
