<!-- @component Model Basics editor: title, manufacturer, game format, production & project dates, production status. -->
<script lang="ts">
  import { untrack } from 'svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import NumberField from '$lib/components/input/NumberField.svelte';
  import MonthSelect from '$lib/components/input/MonthSelect.svelte';
  import Fieldset from '$lib/components/input/Fieldset.svelte';
  import { fetchFieldConstraints, fc, type FieldConstraints } from '$lib/field-constraints';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import {
    EMPTY_EDIT_OPTIONS,
    fetchModelEditOptions,
    toSelectOptions,
    type ModelEditOptions,
  } from './model-edit-options';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  // title/corporate_entity ship as `EntityRef` ({ name, public_id }); `name`
  // seeds the typeahead's label. title is required (NOT NULL on MachineModel).
  type EntityRefData = { public_id: string; name: string } | null | undefined;

  type BasicsModel = {
    production_year?: number | null;
    production_month?: number | null;
    project_year?: number | null;
    project_month?: number | null;
    title?: EntityRefData;
    corporate_entity?: EntityRefData;
    game_format?: { public_id: string } | null;
    production_status?: { public_id: string } | null;
  };

  // `slim` hides the Title picker. Used on single-model combined edit, where
  // re-picking the title isn't allowed — the "Change Title" affordance is
  // deferred to its own section. Manufacturer/Year/Month always show.
  let {
    initialData,
    slug,
    onsaved,
    onerror,
    slim = false,
  }: SectionEditorProps<BasicsModel> & { slim?: boolean } = $props();

  type BasicsFormFields = {
    production_year: string | number;
    production_month: string | number;
    project_year: string | number;
    project_month: string | number;
    title: string;
    game_format: string;
    production_status: string;
  };

  function extractFields(m: BasicsModel): BasicsFormFields {
    return {
      production_year: m.production_year ?? '',
      production_month: m.production_month ?? '',
      project_year: m.project_year ?? '',
      project_month: m.project_month ?? '',
      title: m.title?.public_id ?? '',
      game_format: m.game_format?.public_id ?? '',
      production_status: m.production_status?.public_id ?? '',
    };
  }

  // untrack: intentional one-time capture; component re-mounts when modal reopens
  const initialFields = untrack(() => extractFields(initialData));
  const initialCorporateEntity = untrack(() => initialData.corporate_entity?.public_id ?? '');
  const original = { ...initialFields, corporate_entity: initialCorporateEntity };
  let fields = $state<BasicsFormFields>({ ...initialFields });
  // corporate_entity is optional: bind `string | null`, normalize null → '' at
  // the diff boundary so clearing it diffs as '' → null. title is required.
  let corporateEntity = $state<string | null>(initialCorporateEntity || null);
  let current = $derived({ ...fields, corporate_entity: corporateEntity ?? '' });
  // Hidden fields (slim mode) never mutate because they have no UI, so
  // diffScalarFields naturally ignores them — no explicit strip needed.
  let dirty = $derived(Object.keys(diffScalarFields(current, original)).length > 0);

  let fieldErrors = $state<FieldErrors>({});
  let constraints = $state<FieldConstraints>({});
  let editOptions = $state<ModelEditOptions>(EMPTY_EDIT_OPTIONS);

  function initialSelection(ref: EntityRefData): EntityOption | null {
    return ref ? { value: ref.public_id, label: ref.name } : null;
  }

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

  export { dirty };

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    const changed = diffScalarFields(current, original);

    if (!dirty) {
      onsaved();
      return;
    }

    const result: SaveResult = await saveModelClaims(slug, {
      fields: changed,
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

<div class="basics-grid">
  {#if !slim}
    <EntitySelect
      type="title"
      label="Title"
      bind:selected={fields.title}
      initialSelection={initialSelection(initialData.title)}
      error={fieldErrors.title ?? ''}
      placeholder="Search titles..."
      required
    />
  {/if}
  <EntitySelect
    type="corporate-entity"
    label="Manufacturer"
    bind:selected={corporateEntity}
    initialSelection={initialSelection(initialData.corporate_entity)}
    error={fieldErrors.corporate_entity ?? ''}
    placeholder="Search manufacturers..."
  />
  <div class="date-group">
    <Fieldset legend="Production date">
      <div class="date-fields">
        <NumberField
          label="Year"
          bind:value={fields.production_year}
          error={fieldErrors.production_year ?? ''}
          {...fc(constraints, 'production_year')}
        />
        <MonthSelect
          label="Month"
          bind:value={fields.production_month}
          error={fieldErrors.production_month ?? ''}
        />
      </div>
    </Fieldset>
  </div>
  <div class="date-group">
    <Fieldset legend="Project date">
      <div class="date-fields">
        <NumberField
          label="Year"
          bind:value={fields.project_year}
          error={fieldErrors.project_year ?? ''}
          {...fc(constraints, 'project_year')}
        />
        <MonthSelect
          label="Month"
          bind:value={fields.project_month}
          error={fieldErrors.project_month ?? ''}
        />
      </div>
    </Fieldset>
  </div>
  <SearchableSelect
    label="Game format"
    options={toSelectOptions(editOptions.game_formats ?? [])}
    bind:selected={fields.game_format}
    error={fieldErrors.game_format ?? ''}
    allowZeroCount
    showCounts={false}
    placeholder="Search game formats..."
  />
  <SearchableSelect
    label="Production status"
    options={toSelectOptions(editOptions.production_statuses ?? [])}
    bind:selected={fields.production_status}
    error={fieldErrors.production_status ?? ''}
    allowZeroCount
    showCounts={false}
    placeholder="Search production statuses..."
  />
</div>

<style>
  .basics-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }

  .date-group {
    grid-column: 1 / -1;
  }

  .date-fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }
</style>
