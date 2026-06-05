<script lang="ts">
  import { untrack } from 'svelte';
  import type { CreditSchema } from '$lib/api/schema';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import { creditsChanged } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import {
    EMPTY_EDIT_OPTIONS,
    fetchModelEditOptions,
    toSelectOptions,
    type ModelEditOptions,
  } from './model-edit-options';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  type Credit = CreditSchema;

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<Credit[]> = $props();

  // `initial` is the row's saved person, frozen at creation, so the typeahead
  // renders it on mount without a search. It must NOT track the live
  // `person_slug` — re-seeding the widget with a stale label would overwrite
  // the correct label a (re)selection just cached.
  type KeyedCredit = {
    key: number;
    // The widget can clear this to null at runtime, but it's typed `string`
    // because it *is* the save-payload field (`credits[].person_slug: string`);
    // the truthy filter in save() drops cleared rows. (Single top-level FKs use
    // `string | null` — per-row payload fields stay `string`.)
    person_slug: string;
    role: string;
    initial: EntityOption | null;
  };

  let keyCounter = 0;

  function toKeyedCredits(credits: Credit[]): KeyedCredit[] {
    return credits.map((c) => ({
      key: keyCounter++,
      person_slug: c.person.public_id,
      role: c.role,
      initial: { value: c.person.public_id, label: c.person.name },
    }));
  }

  // untrack: intentional one-time capture; component re-mounts when modal reopens
  const originalCredits = untrack(() => initialData);
  let editCredits = $state<KeyedCredit[]>(untrack(() => toKeyedCredits(initialData)));
  let dirty = $derived.by(() => {
    const original = originalCredits.map((credit) => `${credit.person.public_id}:${credit.role}`);
    const current = editCredits.map((credit) => `${credit.person_slug}:${credit.role}`);
    return JSON.stringify(current) !== JSON.stringify(original);
  });

  let fieldErrors = $state<FieldErrors>({});
  let editOptions = $state<ModelEditOptions>(EMPTY_EDIT_OPTIONS);

  $effect(() => {
    fetchModelEditOptions().then((opts) => {
      editOptions = opts;
    });
  });

  $effect(() => {
    ondirtychange(dirty);
  });

  export function isDirty(): boolean {
    return dirty;
  }

  function addCredit() {
    editCredits = [...editCredits, { key: keyCounter++, person_slug: '', role: '', initial: null }];
  }

  function removeCredit(index: number) {
    editCredits = editCredits.filter((_, i) => i !== index);
  }

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};
    const incompleteRows = editCredits.filter(
      (c) => (c.person_slug && !c.role) || (!c.person_slug && c.role),
    );
    if (incompleteRows.length > 0) {
      for (const row of incompleteRows) {
        if (row.person_slug && !row.role) {
          fieldErrors[`credit_role.${row.person_slug}:`] = 'Select a role.';
        } else {
          fieldErrors[`credit_person.:${row.role}`] = 'Select a person.';
        }
      }
      onerror('Please fix the errors below.');
      return;
    }

    const cleanCredits = editCredits
      .filter((c) => c.person_slug && c.role)
      .map(({ person_slug, role }) => ({ person_slug, role }));

    if (!creditsChanged(cleanCredits, originalCredits)) {
      onsaved();
      return;
    }

    const result: SaveResult = await saveModelClaims(slug, {
      credits: cleanCredits,
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

<div class="people-editor">
  {#each editCredits as credit, i (credit.key)}
    {@const pairError = fieldErrors[`credits.${credit.person_slug}:${credit.role}`] ?? ''}
    {@const personError = fieldErrors[`credit_person.:${credit.role}`] ?? ''}
    {@const roleError = fieldErrors[`credit_role.${credit.person_slug}:`] ?? ''}
    {@const rowError = pairError || personError || roleError}
    <div class="credit-row" class:has-error={!!rowError}>
      <div class="credit-person">
        <EntitySelect
          type="person"
          label=""
          bind:selected={editCredits[i].person_slug}
          initialSelection={credit.initial}
          placeholder="Search people..."
        />
      </div>
      <div class="credit-role">
        <SearchableSelect
          label=""
          options={toSelectOptions(editOptions.credit_roles ?? [])}
          bind:selected={editCredits[i].role}
          allowZeroCount
          showCounts={false}
          placeholder="Role..."
        />
      </div>
      <button type="button" class="remove-btn" onclick={() => removeCredit(i)}>&times;</button>
    </div>
    {#if rowError}
      <p class="row-error" role="alert">{rowError}</p>
    {/if}
  {/each}
  <button
    type="button"
    class="add-btn"
    disabled={editCredits.some((c) => !c.person_slug || !c.role)}
    onclick={addCredit}
  >
    Add credit
  </button>
</div>

<style>
  .people-editor {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .credit-row {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: var(--size-2);
    align-items: end;
  }

  .credit-role {
    width: 10rem;
  }

  .row-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: 0;
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
