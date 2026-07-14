<!--
@component
Related-models section editor: a flat, inline-editable list — one row per
relationship. Each row picks a kind (the variant/remake lineage FKs, or a
copy/conversion/conversion-kit edge), a target machine (or, for edges, a
free-text label when the donor isn't in the catalog) and — for edges — a
license. "Add relationship" appends a blank row; the modal's footer Save
commits the whole diff as one ChangeSet, so a single citation rides every
changed claim. Mirrors PeopleEditor's inline-list pattern.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import type { ModelRelationshipSchema } from '$lib/api/schema';
  import {
    machineTargetText,
    type LicenseStatus,
    type RelationshipKind,
  } from '$lib/entities/relationship-phrase';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  type HierarchyRef = { public_id: string; name?: string } | null | undefined;

  type RelatedModelsModel = {
    variant_of?: HierarchyRef;
    remake_of?: HierarchyRef;
    relationships?: ModelRelationshipSchema[];
  };

  let { initialData, slug, onsaved, onerror }: SectionEditorProps<RelatedModelsModel> = $props();

  const EDGE_KINDS = ['copy', 'conversion', 'conversion_kit'] as const;
  type EdgeKind = (typeof EDGE_KINDS)[number];
  const SINGLE_KINDS = ['variant', 'remake'] as const;

  // Phrase-style labels so a row reads like its reader phrasing: "Copy of
  // [Galaxie] Unlicensed". Order runs lineage FKs first, then the edges.
  const KIND_OPTIONS: { value: RelationshipKind; label: string }[] = [
    { value: 'variant', label: 'Variant of' },
    { value: 'remake', label: 'Remake of' },
    { value: 'copy', label: 'Copy of' },
    { value: 'conversion', label: 'Conversion of' },
    { value: 'conversion_kit', label: 'Conversion kit for' },
  ];

  // `satisfies` binds the option list to the wire union — an out-of-vocab
  // value fails the build (a *new* backend value still needs adding here).
  const LICENSE_OPTIONS = [
    { value: 'unknown', label: 'License unknown' },
    { value: 'licensed', label: 'Licensed' },
    { value: 'unlicensed', label: 'Unlicensed' },
  ] as const satisfies readonly { value: LicenseStatus; label: string }[];

  // '' is the unchosen state a freshly-added row starts in, so the user must
  // pick a kind rather than silently inheriting a default.
  type RowKind = RelationshipKind | '';

  type Row = {
    key: number;
    kind: RowKind;
    // Machine target's `public_id`; typed `string` because it *is* the
    // save-payload field, though EntitySelect clears it to null at runtime.
    targetSlug: string;
    targetLabel: string; // free-text edge target (used when `useLabel`)
    useLabel: boolean; // edge-only: describe the donor instead of picking it
    license: LicenseStatus; // edges only; 'unknown' and ignored for variant/remake
    // Saved target, frozen at creation, so EntitySelect renders it on mount
    // without a search. Must NOT track the live `targetSlug`.
    initial: EntityOption | null;
  };

  let keyCounter = 0;

  function hierarchyRows(kind: 'variant' | 'remake', ref: HierarchyRef): Row[] {
    if (!ref) return [];
    return [
      {
        key: keyCounter++,
        kind,
        targetSlug: ref.public_id,
        targetLabel: '',
        useLabel: false,
        license: 'unknown',
        initial: { value: ref.public_id, label: ref.name ?? ref.public_id },
      },
    ];
  }

  function edgeRow(edge: ModelRelationshipSchema): Row {
    const targetSlug = edge.target_machine?.public_id ?? '';
    return {
      key: keyCounter++,
      kind: edge.relationship_type,
      targetSlug,
      targetLabel: edge.target_label ?? '',
      useLabel: !targetSlug && !!edge.target_label,
      license: edge.license_status,
      initial: edge.target_machine
        ? { value: targetSlug, label: machineTargetText(edge.target_machine) }
        : null,
    };
  }

  // untrack: intentional one-time capture; component re-mounts on modal reopen.
  const original = untrack(() => ({
    variant_of: initialData.variant_of?.public_id ?? '',
    remake_of: initialData.remake_of?.public_id ?? '',
  }));
  let rows = $state<Row[]>(
    untrack(() => [
      ...hierarchyRows('variant', initialData.variant_of),
      ...hierarchyRows('remake', initialData.remake_of),
      ...(initialData.relationships ?? []).map(edgeRow),
    ]),
  );

  let fieldErrors = $state<FieldErrors>({});

  function isEdge(kind: RowKind): kind is EdgeKind {
    return (EDGE_KINDS as readonly string[]).includes(kind);
  }

  /** The row's effective target text: the label for a describe-it edge, else the machine slug. */
  function rowTarget(row: Row): string {
    if (isEdge(row.kind) && row.useLabel) return row.targetLabel.trim();
    return row.targetSlug || '';
  }

  function isComplete(row: Row): boolean {
    return row.kind !== '' && rowTarget(row).length > 0;
  }

  /** Variant/remake are single-valued: block the kind if another row already holds it. */
  function kindTaken(kind: RowKind, exceptKey: number): boolean {
    return (
      (SINGLE_KINDS as readonly string[]).includes(kind) &&
      rows.some((r) => r.key !== exceptKey && r.kind === kind)
    );
  }

  function addRow() {
    rows = [
      ...rows,
      {
        key: keyCounter++,
        kind: '',
        targetSlug: '',
        targetLabel: '',
        useLabel: false,
        license: 'unknown',
        initial: null,
      },
    ];
  }

  function removeRow(index: number) {
    rows = rows.filter((_, i) => i !== index);
  }

  let hasIncomplete = $derived(rows.some((r) => !isComplete(r)));

  function rowError(row: Row): string {
    return fieldErrors[`relationships.${rowTarget(row)}`] ?? '';
  }

  // --- dirty + save ------------------------------------------------------------

  function currentFields() {
    const complete = rows.filter(isComplete);
    return {
      variant_of: complete.find((r) => r.kind === 'variant')?.targetSlug ?? '',
      remake_of: complete.find((r) => r.kind === 'remake')?.targetSlug ?? '',
    };
  }

  function edgeSignatures(list: Row[]): string[] {
    return list
      .filter((r) => isEdge(r.kind) && isComplete(r))
      .map((r) => {
        const useLabel = r.useLabel;
        return `${r.kind}|${useLabel ? '' : r.targetSlug || ''}|${useLabel ? r.targetLabel.trim() : ''}|${r.license}`;
      })
      .sort();
  }

  const originalEdgeSignatures = untrack(() => edgeSignatures(rows));

  let dirty = $derived.by(() => {
    const fieldsChanged = Object.keys(diffScalarFields(currentFields(), original)).length > 0;
    const edgesChanged =
      JSON.stringify(edgeSignatures(rows)) !== JSON.stringify(originalEdgeSignatures);
    return fieldsChanged || edgesChanged;
  });

  export { dirty };

  export async function save(meta?: SaveMeta): Promise<void> {
    fieldErrors = {};

    // Reject two edges pointing at the same kind+target (license aside).
    const edges = rows.filter((r) => isEdge(r.kind) && isComplete(r));
    const dupKeys = edges.map(
      (r) =>
        `${r.kind}|${r.useLabel ? '' : r.targetSlug || ''}|${r.useLabel ? r.targetLabel.trim() : ''}`,
    );
    if (new Set(dupKeys).size !== dupKeys.length) {
      onerror('Two relationships have the same kind and target.');
      return;
    }

    if (!dirty) {
      onsaved();
      return;
    }

    const changedFields = diffScalarFields(currentFields(), original);
    const edgesChanged =
      JSON.stringify(edgeSignatures(rows)) !== JSON.stringify(originalEdgeSignatures);
    const body: Parameters<typeof saveModelClaims>[1] = { ...meta };
    if (Object.keys(changedFields).length > 0) body.fields = changedFields;
    if (edgesChanged) {
      body.relationships = edges.map((r) => ({
        relationship_type: r.kind as EdgeKind,
        license_status: r.license,
        target_slug: r.useLabel ? '' : r.targetSlug || '',
        target_label: r.useLabel ? r.targetLabel.trim() : '',
      }));
    }

    const result: SaveResult = await saveModelClaims(slug, body);
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

<div class="related-models-editor">
  {#if rows.length === 0}
    <p class="empty">No related models yet.</p>
  {/if}

  {#each rows as row, i (row.key)}
    {@const edge = isEdge(row.kind)}
    <!-- Progressive disclosure: a new row shows only the kind until one is
         chosen, since the kind decides which other fields the row even has. -->
    <div class="rel-row" class:unset={row.kind === ''}>
      <div class="rel-kind">
        <select aria-label="Relationship kind" bind:value={rows[i].kind}>
          <option value="" disabled>Choose relationship…</option>
          {#each KIND_OPTIONS as opt (opt.value)}
            <option value={opt.value} disabled={kindTaken(opt.value, row.key)}>{opt.label}</option>
          {/each}
        </select>
      </div>

      {#if row.kind !== ''}
        <div class="rel-target">
          {#if edge && row.useLabel}
            <input
              type="text"
              aria-label="Describe the target"
              bind:value={rows[i].targetLabel}
              maxlength="300"
              placeholder="e.g. several Gottlieb EM models"
            />
            <button type="button" class="toggle-btn" onclick={() => (rows[i].useLabel = false)}>
              Pick a machine from the catalog instead
            </button>
          {:else}
            <EntitySelect
              type="model"
              label=""
              bind:selected={rows[i].targetSlug}
              initialSelection={row.initial}
              exclude={[slug]}
              placeholder="Search models..."
            />
            {#if edge}
              <button type="button" class="toggle-btn" onclick={() => (rows[i].useLabel = true)}>
                Not in the catalog, or several machines? Describe it
              </button>
            {/if}
          {/if}
        </div>

        {#if edge}
          <div class="rel-license">
            <select aria-label="License status" bind:value={rows[i].license}>
              {#each LICENSE_OPTIONS as opt (opt.value)}
                <option value={opt.value}>{opt.label}</option>
              {/each}
            </select>
          </div>
        {/if}
      {/if}

      <button
        type="button"
        class="remove-btn"
        aria-label="Remove relationship"
        onclick={() => removeRow(i)}>&times;</button
      >
    </div>
    {#if rowError(row)}
      <p class="row-error" role="alert">{rowError(row)}</p>
    {/if}
  {/each}

  <button type="button" class="add-btn" disabled={hasIncomplete} onclick={addRow}>
    Add relationship
  </button>
</div>

<style>
  .related-models-editor {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .empty {
    color: var(--color-text-muted);
    margin: 0;
  }

  /* Wide: one aligned grid — kind | target | license | remove. Named areas
     keep the columns lined up even on variant/remake rows, which omit the
     license cell. */
  .rel-row {
    display: grid;
    grid-template-columns: 11.5rem minmax(0, 1fr) 11rem auto;
    grid-template-areas: 'kind target license remove';
    gap: var(--size-2);
    align-items: start;
  }

  /* Before a kind is chosen the row has only the dropdown: keep the remove
     button beside it rather than stranded across empty target/license tracks. */
  .rel-row.unset {
    grid-template-columns: 11.5rem auto 1fr;
    grid-template-areas: 'kind remove .';
  }

  .rel-kind {
    grid-area: kind;
  }

  .rel-license {
    grid-area: license;
  }

  .rel-kind select,
  .rel-license select {
    width: 100%;
    /* Native selects ignore line-height for sizing, so they render ~2px
       shorter than the combobox input beside them. Pin the height to the
       input's box formula (1.5 line-height + vertical padding + borders) so
       the row's controls align top and bottom. */
    min-height: calc(1.5em + 2 * var(--size-2) + 2px);
  }

  .rel-target {
    grid-area: target;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  /* Narrow: the three controls can't share a line — stack them into a card,
     remove pinned to the corner. */
  @container (max-width: 30rem) {
    .rel-row {
      display: flex;
      flex-direction: column;
      align-items: stretch;
      position: relative;
      padding: var(--size-3);
      padding-right: calc(var(--size-3) + 2.75rem);
      border: 1px solid var(--color-border-soft);
      border-radius: var(--radius-2);
    }
  }

  .toggle-btn {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    text-decoration: underline;
    text-align: left;
  }

  .row-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: 0;
  }

  .remove-btn {
    grid-area: remove;
    background: none;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: 0.5rem 0.7rem;
    cursor: pointer;
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    line-height: 1;
  }

  .remove-btn:hover {
    color: var(--color-error-text);
    border-color: var(--color-error-text);
  }

  @container (max-width: 30rem) {
    .remove-btn {
      position: absolute;
      top: var(--size-3);
      right: var(--size-3);
    }
  }

  .add-btn {
    background: none;
    border: 1px dashed var(--color-border-soft);
    border-radius: var(--radius-2);
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
