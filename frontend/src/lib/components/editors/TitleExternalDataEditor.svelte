<script lang="ts">
  import { untrack } from 'svelte';
  import NumberField from '$lib/components/input/NumberField.svelte';
  import TextField from '$lib/components/input/TextField.svelte';
  import { fetchFieldConstraints, fc, type FieldConstraints } from '$lib/field-constraints';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from './editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type { SaveResult, SaveMeta } from './save-claims-shared';
  import { saveTitleClaims } from './save-title-claims';

  type ExternalDataTitle = {
    opdb_id?: string | null;
    fandom_page_id?: number | null;
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<ExternalDataTitle> = $props();

  type ExternalDataFormFields = {
    opdb_id: string;
    fandom_page_id: string | number;
  };

  function extractFields(t: ExternalDataTitle): ExternalDataFormFields {
    return {
      opdb_id: t.opdb_id ?? '',
      fandom_page_id: t.fandom_page_id ?? '',
    };
  }

  const original = untrack(() => extractFields(initialData));
  let fields = $state<ExternalDataFormFields>({ ...original });
  let dirty = $derived.by(() => Object.keys(diffScalarFields(fields, original)).length > 0);

  let fieldErrors = $state<FieldErrors>({});
  let constraints = $state<FieldConstraints>({});

  $effect(() => {
    fetchFieldConstraints('title').then((c) => {
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
    const changed = diffScalarFields(fields, original);

    if (!dirty) {
      onsaved();
      return;
    }

    const result: SaveResult = await saveTitleClaims(slug, {
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

<div class="external-data-editor">
  <div class="fields-grid">
    <TextField
      label="OPDB Group ID"
      bind:value={fields.opdb_id}
      error={fieldErrors.opdb_id ?? ''}
    />
    <NumberField
      label="Fandom Page ID"
      bind:value={fields.fandom_page_id}
      error={fieldErrors.fandom_page_id ?? ''}
      {...fc(constraints, 'fandom_page_id')}
    />
  </div>
</div>

<style>
  .external-data-editor {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .fields-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-3);
  }
</style>
