<script lang="ts">
  import { untrack } from 'svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import NumberField from '$lib/components/input/NumberField.svelte';
  import MonthSelect from '$lib/components/input/MonthSelect.svelte';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { diffScalarFields } from '$lib/edit-helpers';
  import { fetchFieldConstraints, fc, type FieldConstraints } from '$lib/field-constraints';
  import type { PersonEditView } from './person-edit-types';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { savePersonClaims, type SaveResult, type SaveMeta } from './save-person-claims';

  type DetailsFields = {
    nationality: string;
    birth_year: string | number;
    birth_month: string | number;
    birth_day: string | number;
    birth_place: string;
    death_year: string | number;
    death_month: string | number;
    death_day: string | number;
    photo_url: string;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<PersonEditView> = $props();

  function extractFields(person: PersonEditView): DetailsFields {
    return {
      nationality: person.nationality ?? '',
      birth_year: person.birth_year ?? '',
      birth_month: person.birth_month ?? '',
      birth_day: person.birth_day ?? '',
      birth_place: person.birth_place ?? '',
      death_year: person.death_year ?? '',
      death_month: person.death_month ?? '',
      death_day: person.death_day ?? '',
      photo_url: person.photo_url ?? '',
    };
  }

  const original = untrack(() => extractFields(initialData));
  let fields = $state<DetailsFields>({ ...original });
  let fieldErrors = $state<FieldErrors>({});
  let changedFields = $derived(diffScalarFields(fields, original));
  let dirty = $derived(Object.keys(changedFields).length > 0);

  let constraints = $state<FieldConstraints>({});

  $effect(() => {
    fetchFieldConstraints('person').then((c) => {
      constraints = c;
    });
  });

  $effect(() => {
    ondirtychange(dirty);
  });

  export function isDirty(): boolean {
    return dirty;
  }

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    if (!dirty) {
      onsaved();
      return;
    }

    const result: SaveResult = await savePersonClaims(slug, {
      fields: changedFields,
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

<div class="editor-fields">
  <TextField
    label="Nationality"
    bind:value={fields.nationality}
    error={fieldErrors.nationality ?? ''}
  />

  <TextField
    label="Birth place"
    bind:value={fields.birth_place}
    error={fieldErrors.birth_place ?? ''}
  />

  <fieldset class="date-group">
    <legend>Born</legend>
    <div class="date-row">
      <NumberField
        label="Year"
        bind:value={fields.birth_year}
        error={fieldErrors.birth_year ?? ''}
        {...fc(constraints, 'birth_year')}
      />
      <MonthSelect
        label="Month"
        bind:value={fields.birth_month}
        error={fieldErrors.birth_month ?? ''}
      />
      <NumberField
        label="Day"
        bind:value={fields.birth_day}
        error={fieldErrors.birth_day ?? ''}
        {...fc(constraints, 'birth_day')}
      />
    </div>
  </fieldset>

  <fieldset class="date-group">
    <legend>Died</legend>
    <div class="date-row">
      <NumberField
        label="Year"
        bind:value={fields.death_year}
        error={fieldErrors.death_year ?? ''}
        {...fc(constraints, 'death_year')}
      />
      <MonthSelect
        label="Month"
        bind:value={fields.death_month}
        error={fieldErrors.death_month ?? ''}
      />
      <NumberField
        label="Day"
        bind:value={fields.death_day}
        error={fieldErrors.death_day ?? ''}
        {...fc(constraints, 'death_day')}
      />
    </div>
  </fieldset>

  <TextField
    label="Photo URL"
    type="url"
    bind:value={fields.photo_url}
    error={fieldErrors.photo_url ?? ''}
  />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .date-group {
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-3);
    margin: 0;
  }

  .date-group legend {
    font-size: var(--font-size-1);
    font-weight: 500;
    color: var(--color-text-muted);
    padding: 0 var(--size-1);
  }

  .date-row {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: var(--size-3);
  }
</style>
