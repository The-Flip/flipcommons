<script lang="ts">
  import { untrack } from 'svelte';
  import NumberField from '$lib/components/input/NumberField.svelte';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { diffScalarFields } from '$lib/edit-helpers';
  import { fetchFieldConstraints, fc, type FieldConstraints } from '$lib/field-constraints';
  import type { CorporateEntityEditView } from './corporate-entity-edit-types';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import {
    saveCorporateEntityClaims,
    type SaveMeta,
    type SaveResult,
  } from './save-corporate-entity-claims';

  type BasicsFields = {
    year_start: string | number;
    year_end: string | number;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<CorporateEntityEditView> = $props();

  function extractFields(entity: CorporateEntityEditView): BasicsFields {
    return {
      year_start: entity.year_start ?? '',
      year_end: entity.year_end ?? '',
    };
  }

  const original = untrack(() => extractFields(initialData));
  let fields = $state<BasicsFields>({ ...original });
  let fieldErrors = $state<FieldErrors>({});
  let constraints = $state<FieldConstraints>({});
  let changedFields = $derived(diffScalarFields(fields, original));
  let dirty = $derived(Object.keys(changedFields).length > 0);

  $effect(() => {
    fetchFieldConstraints('corporate-entity').then((c) => {
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

    const result: SaveResult = await saveCorporateEntityClaims(slug, {
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
  <NumberField
    label="Established"
    bind:value={fields.year_start}
    error={fieldErrors.year_start ?? ''}
    {...fc(constraints, 'year_start')}
  />
  <NumberField
    label="Ceased operations"
    bind:value={fields.year_end}
    error={fieldErrors.year_end ?? ''}
    {...fc(constraints, 'year_end')}
  />
</div>

<style>
  .editor-fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }
</style>
