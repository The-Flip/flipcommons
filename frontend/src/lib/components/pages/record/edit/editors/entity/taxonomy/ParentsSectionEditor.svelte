<script lang="ts">
  import { untrack } from 'svelte';
  import EntityMultiSelect from '$lib/components/input/entity-select/EntityMultiSelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { publicIdSetChanged } from '$lib/edit-helpers';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type {
    SaveMeta,
    SaveResult,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';

  type ParentRef = { public_id: string; name?: string };

  type ParentsData = { parents: ParentRef[] };

  type SaveBody = {
    parents: string[];
  } & SaveMeta;

  type SaveFn = (slug: string, body: SaveBody) => Promise<SaveResult>;

  let {
    initialData,
    slug,
    save: saveFn,
    onsaved,
    onerror,
    ondirtychange = () => {},
    type,
    label = 'Parents',
    placeholder = 'Search...',
  }: SectionEditorProps<ParentsData> & {
    save: SaveFn;
    /** Autocomplete registry key for the parent entity (`theme`, `gameplay-feature`). */
    type: string;
    label?: string;
    placeholder?: string;
  } = $props();

  const originalParents: ParentRef[] = untrack(() => initialData.parents.map((p) => ({ ...p })));
  let selectedParents = $state<string[]>(originalParents.map((p) => p.public_id));
  // Seed chips so saved parents render on mount with no search.
  const initialSelections: EntityOption[] = untrack(() =>
    originalParents.map((p) => ({ value: p.public_id, label: p.name ?? p.public_id })),
  );
  let fieldErrors = $state<FieldErrors>({});
  let dirty = $derived(publicIdSetChanged(selectedParents, originalParents));

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

    const body: SaveBody = { parents: selectedParents, ...meta };
    const result = await saveFn(slug, body);

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
  <EntityMultiSelect
    {type}
    {label}
    bind:selected={selectedParents}
    {initialSelections}
    exclude={[slug]}
    {placeholder}
    error={fieldErrors.parents ?? ''}
  />
</div>

<style>
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }
</style>
