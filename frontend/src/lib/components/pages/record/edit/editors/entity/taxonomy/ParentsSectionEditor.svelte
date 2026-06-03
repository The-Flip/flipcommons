<script lang="ts">
  import { untrack } from 'svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import { publicIdSetChanged } from '$lib/edit-helpers';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import type {
    SaveMeta,
    SaveResult,
  } from '$lib/components/pages/record/edit/editors/save-claims-shared';

  type ParentRef = { public_id: string; name?: string };
  type ParentOption = { slug: string; label: string; count?: number };

  type ParentsData = { parents: ParentRef[] };

  type SaveBody = {
    parents: string[];
  } & SaveMeta;

  type SaveFn = (slug: string, body: SaveBody) => Promise<SaveResult>;

  type OptionsLoader = () => Promise<ParentOption[]>;

  let {
    initialData,
    slug,
    save: saveFn,
    onsaved,
    onerror,
    ondirtychange = () => {},
    optionsLoader,
    label = 'Parents',
    placeholder = 'Search...',
  }: SectionEditorProps<ParentsData> & {
    save: SaveFn;
    optionsLoader: OptionsLoader;
    label?: string;
    placeholder?: string;
  } = $props();

  const originalParents: ParentRef[] = untrack(() => initialData.parents.map((p) => ({ ...p })));
  let selectedParents = $state<string[]>(originalParents.map((p) => p.public_id));
  let parentOptions = $state<ParentOption[]>([]);
  // Map the parent's identity `slug` onto the control's opaque `value` at the boundary.
  let selectOptions = $derived(
    parentOptions.map((o) => ({ value: o.slug, label: o.label, count: o.count })),
  );
  let fieldErrors = $state<FieldErrors>({});
  let dirty = $derived(publicIdSetChanged(selectedParents, originalParents));

  $effect(() => {
    const currentSlug = untrack(() => slug);
    optionsLoader().then((opts) => {
      parentOptions = opts.filter((opt) => opt.slug !== currentSlug);
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
  <SearchableSelect
    {label}
    options={selectOptions}
    bind:selected={selectedParents}
    multi
    allowZeroCount
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
