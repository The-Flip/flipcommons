<!--
@component
Related-models section editor: one batched list over every relationship kind —
variant/remake (scalar lineage FKs) and copy/conversion/conversion-kit edges
(the ModelRelationship table). Rows render as reader-facing phrases ("Bootleg
of Galaxie (Gottlieb 1971)"); Add walks kind-picker → brief form; the footer
Save commits the whole diff as one ChangeSet, so a single citation rides every
changed claim.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import EntitySelect from '$lib/components/input/entity-select/EntitySelect.svelte';
  import type { EntityOption } from '$lib/api/entity-autocomplete';
  import type { ModelRef, ModelRelationshipSchema } from '$lib/api/schema';
  import {
    machineTargetText,
    relationshipLead,
    type LicenseStatus,
    type RelationshipKind,
  } from '$lib/entities/relationship-phrase';
  import { diffScalarFields } from '$lib/edit-helpers';
  import type { SectionEditorProps } from '$lib/components/pages/record/edit/editors/editor-contract';
  import type { FieldErrors } from '$lib/api/parse-api-error';
  import DirtyRow from '$lib/components/pages/record/edit/editors/DirtyRow.svelte';
  import { saveModelClaims, type SaveResult, type SaveMeta } from './save-model-claims';

  type HierarchyRef = { public_id: string; name?: string } | null | undefined;

  type RelatedModelsModel = {
    variant_of?: HierarchyRef;
    remake_of?: HierarchyRef;
    relationships?: ModelRelationshipSchema[];
  };

  let {
    initialData,
    slug,
    onsaved,
    onerror,
    ondirtychange = () => {},
  }: SectionEditorProps<RelatedModelsModel> = $props();

  const EDGE_KINDS = ['copy', 'conversion', 'conversion_kit'] as const;
  type EdgeKind = (typeof EDGE_KINDS)[number];
  const SINGLE_KINDS = ['variant', 'remake'] as const;

  const KIND_CARDS: {
    kind: RelationshipKind;
    name: string;
    description: string;
    example: string;
  }[] = [
    {
      kind: 'variant',
      name: 'Variant',
      description:
        'The same game re-dressed. Shares the same gameplay, differing only in cosmetics (cabinet art, numbered plaques, toppers, colored plastics).',
      example: '',
    },
    {
      kind: 'remake',
      name: 'Remake',
      description: 'A later re-manufacture of the original machine.',
      example: 'Like a modern reissue decades after the original.',
    },
    {
      kind: 'copy',
      name: 'Copy',
      description:
        "Reproduces another machine's design on freshly-built hardware. Whether it was authorized is a separate field, so bootlegs and licensed reproductions are both copies.",
      example: "Like RMG's Galaxie: a new cabinet running Gottlieb's Galaxie playfield.",
    },
    {
      kind: 'conversion',
      name: 'Conversion',
      description:
        'A finished machine physically built out of one or more donor machines — reusing their cabinets or parts. Not a kit you sell.',
      example: 'Like j-martina, rebuilt from whatever used cabinets were on hand.',
    },
    {
      kind: 'conversion_kit',
      name: 'Conversion kit',
      description:
        'Parts sold to convert one machine into a different one. Often fits several donors.',
      example: 'Like a Geiger kit that retrofits a Gottlieb machine in the field.',
    },
  ];

  // `satisfies` binds the option list to the wire union — an out-of-vocab
  // value fails the build (a *new* backend value still needs adding here).
  const LICENSE_OPTIONS = [
    { value: 'unknown', label: 'Unknown' },
    { value: 'licensed', label: 'Licensed' },
    { value: 'unlicensed', label: 'Unlicensed' },
  ] as const satisfies readonly { value: LicenseStatus; label: string }[];

  type Row = {
    key: number;
    kind: RelationshipKind;
    targetSlug: string; // '' on the label rung
    targetLabel: string; // '' on the machine rung
    targetDisplay: string; // human text for machine targets
    license: LicenseStatus; // 'unknown' (ignored) for variant/remake
    removed: boolean;
    original: string | null; // saved signature; null = added this session
  };

  function signature(row: Pick<Row, 'kind' | 'targetSlug' | 'targetLabel' | 'license'>): string {
    return `${row.kind}|${row.targetSlug}|${row.targetLabel}|${row.license}`;
  }

  let keyCounter = 0;

  function hierarchyRow(kind: 'variant' | 'remake', ref: HierarchyRef): Row[] {
    if (!ref) return [];
    const row: Row = {
      key: keyCounter++,
      kind,
      targetSlug: ref.public_id,
      targetLabel: '',
      targetDisplay: ref.name ?? ref.public_id,
      license: 'unknown',
      removed: false,
      original: null,
    };
    row.original = signature(row);
    return [row];
  }

  function edgeRow(edge: ModelRelationshipSchema): Row {
    const row: Row = {
      key: keyCounter++,
      kind: edge.relationship_type as EdgeKind,
      targetSlug: edge.target_machine?.public_id ?? '',
      targetLabel: edge.target_label ?? '',
      targetDisplay: edge.target_machine ? machineTargetText(edge.target_machine as ModelRef) : '',
      license: edge.license_status as LicenseStatus,
      removed: false,
      original: null,
    };
    row.original = signature(row);
    return row;
  }

  // untrack: intentional one-time capture; component re-mounts on modal reopen.
  const original = untrack(() => ({
    variant_of: initialData.variant_of?.public_id ?? '',
    remake_of: initialData.remake_of?.public_id ?? '',
  }));
  let rows = $state<Row[]>(
    untrack(() => [
      ...hierarchyRow('variant', initialData.variant_of),
      ...hierarchyRow('remake', initialData.remake_of),
      ...(initialData.relationships ?? []).map(edgeRow),
    ]),
  );

  // --- sub-views -------------------------------------------------------------

  type View = 'list' | 'picker' | 'form';
  let view = $state<View>('list');
  let editingKey = $state<number | null>(null);
  let formKind = $state<RelationshipKind>('copy');
  let formTargetSlug = $state<string | null>(null);
  let formTargetInitial = $state<EntityOption | null>(null);
  let formTargetDisplay = $state('');
  let formUseLabel = $state(false);
  let formLabel = $state('');
  let formLicense = $state<LicenseStatus>('unknown');
  let formError = $state('');

  let fieldErrors = $state<FieldErrors>({});

  function isEdge(kind: RelationshipKind): kind is EdgeKind {
    return (EDGE_KINDS as readonly string[]).includes(kind);
  }

  function liveRows(): Row[] {
    return rows.filter((r) => !r.removed);
  }

  /** Variant/remake are single-valued: block a second live row of that kind. */
  function kindDisabled(kind: RelationshipKind): boolean {
    return (
      (SINGLE_KINDS as readonly string[]).includes(kind) && liveRows().some((r) => r.kind === kind)
    );
  }

  function openAddForm(kind: RelationshipKind) {
    editingKey = null;
    formKind = kind;
    formTargetSlug = null;
    formTargetInitial = null;
    formTargetDisplay = '';
    formUseLabel = false;
    formLabel = '';
    formLicense = 'unknown';
    formError = '';
    view = 'form';
  }

  function openEditForm(row: Row) {
    editingKey = row.key;
    formKind = row.kind;
    formTargetSlug = row.targetSlug || null;
    formTargetInitial = row.targetSlug
      ? { value: row.targetSlug, label: row.targetDisplay || row.targetSlug }
      : null;
    formTargetDisplay = row.targetDisplay;
    formUseLabel = !row.targetSlug && !!row.targetLabel;
    formLabel = row.targetLabel;
    formLicense = row.license;
    formError = '';
    view = 'form';
  }

  function commitForm() {
    const useLabel = isEdge(formKind) && formUseLabel;
    const targetSlug = useLabel ? '' : (formTargetSlug ?? '');
    const targetLabel = useLabel ? formLabel.trim() : '';
    if (!targetSlug && !targetLabel) {
      formError = useLabel ? 'Describe the target.' : 'Select a target machine.';
      return;
    }
    const duplicate = liveRows().some(
      (r) =>
        r.key !== editingKey &&
        isEdge(r.kind) &&
        isEdge(formKind) &&
        r.targetSlug === targetSlug &&
        r.targetLabel === targetLabel,
    );
    if (duplicate) {
      formError = 'A relationship with this target already exists.';
      return;
    }
    const patch = {
      kind: formKind,
      targetSlug,
      targetLabel,
      targetDisplay: useLabel ? '' : formTargetDisplay,
      license: isEdge(formKind) ? formLicense : ('unknown' as const),
    };
    if (editingKey === null) {
      rows = [...rows, { key: keyCounter++, ...patch, removed: false, original: null }];
    } else {
      rows = rows.map((r) => (r.key === editingKey ? { ...r, ...patch } : r));
    }
    view = 'list';
  }

  function removeRow(row: Row) {
    // An added row cancels outright; a saved row is struck through with Undo.
    rows =
      row.original === null
        ? rows.filter((r) => r.key !== row.key)
        : rows.map((r) => (r.key === row.key ? { ...r, removed: true } : r));
  }

  function undoRemove(row: Row) {
    rows = rows.map((r) => (r.key === row.key ? { ...r, removed: false } : r));
  }

  function rowStatus(row: Row): 'unchanged' | 'added' | 'changed' | 'removed' {
    if (row.removed) return 'removed';
    if (row.original === null) return 'added';
    return signature(row) === row.original ? 'unchanged' : 'changed';
  }

  function rowText(row: Row): string {
    const target = row.targetSlug ? row.targetDisplay || row.targetSlug : row.targetLabel;
    return `${relationshipLead(row.kind, row.license)} ${target}`;
  }

  function rowError(row: Row): string {
    return fieldErrors[`relationships.${row.targetSlug || row.targetLabel}`] ?? '';
  }

  // --- dirty + save ------------------------------------------------------------

  function currentFields() {
    const live = liveRows();
    return {
      variant_of: live.find((r) => r.kind === 'variant')?.targetSlug ?? '',
      remake_of: live.find((r) => r.kind === 'remake')?.targetSlug ?? '',
    };
  }

  function edgeSignatures(list: Row[]): string[] {
    return list
      .filter((r) => isEdge(r.kind))
      .map(signature)
      .sort();
  }

  const originalEdgeSignatures = untrack(() => edgeSignatures(rows));

  let dirty = $derived.by(() => {
    const fieldsChanged = Object.keys(diffScalarFields(currentFields(), original)).length > 0;
    const edgesChanged =
      JSON.stringify(edgeSignatures(liveRows())) !== JSON.stringify(originalEdgeSignatures);
    return fieldsChanged || edgesChanged;
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
    const changedFields = diffScalarFields(currentFields(), original);
    const edgesChanged =
      JSON.stringify(edgeSignatures(liveRows())) !== JSON.stringify(originalEdgeSignatures);
    const body: Parameters<typeof saveModelClaims>[1] = { ...meta };
    if (Object.keys(changedFields).length > 0) body.fields = changedFields;
    if (edgesChanged) {
      body.relationships = liveRows()
        .filter((r) => isEdge(r.kind))
        .map((r) => ({
          relationship_type: r.kind as EdgeKind,
          license_status: r.license,
          target_slug: r.targetSlug,
          target_label: r.targetLabel,
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
  {#if view === 'list'}
    {#if rows.length === 0}
      <p class="empty">No related models yet.</p>
    {/if}
    {#each rows as row (row.key)}
      <div>
        <DirtyRow status={rowStatus(row)} onundo={() => undoRemove(row)}>
          <button type="button" class="row-text" onclick={() => openEditForm(row)}>
            {rowText(row)}
          </button>
          {#snippet actions()}
            <button
              type="button"
              class="remove-btn"
              aria-label="Remove {rowText(row)}"
              onclick={() => removeRow(row)}>&times;</button
            >
          {/snippet}
        </DirtyRow>
        {#if rowError(row)}
          <p class="row-error" role="alert">{rowError(row)}</p>
        {/if}
      </div>
    {/each}
    <button type="button" class="add-btn" onclick={() => (view = 'picker')}>
      Add relationship
    </button>
  {:else if view === 'picker'}
    <p class="picker-heading">What kind of relationship?</p>
    <div class="kind-cards">
      {#each KIND_CARDS as card (card.kind)}
        <button
          type="button"
          class="kind-card"
          disabled={kindDisabled(card.kind)}
          onclick={() => openAddForm(card.kind)}
        >
          <span class="kind-name">{card.name}</span>
          <span class="kind-description">{card.description}</span>
          {#if card.example}
            <span class="kind-example">{card.example}</span>
          {/if}
          {#if kindDisabled(card.kind)}
            <span class="kind-note">Already set — edit the existing row.</span>
          {/if}
        </button>
      {/each}
    </div>
    <button type="button" class="back-btn" onclick={() => (view = 'list')}>Back</button>
  {:else}
    <div class="edge-form">
      {#if editingKey !== null && isEdge(formKind)}
        <label class="form-field">
          <span class="field-label">Kind</span>
          <select bind:value={formKind}>
            {#each KIND_CARDS.filter((c) => isEdge(c.kind)) as card (card.kind)}
              <option value={card.kind}>{card.name}</option>
            {/each}
          </select>
        </label>
      {/if}

      {#if isEdge(formKind) && formUseLabel}
        <label class="form-field">
          <span class="field-label">Describe the target</span>
          <input
            type="text"
            bind:value={formLabel}
            maxlength="300"
            placeholder="e.g. several Gottlieb EM models"
          />
        </label>
        <button type="button" class="toggle-btn" onclick={() => (formUseLabel = false)}>
          Pick a machine from the catalog instead
        </button>
      {:else}
        <EntitySelect
          type="model"
          label="Target machine"
          bind:selected={formTargetSlug}
          initialSelection={formTargetInitial}
          exclude={[slug]}
          placeholder="Search models..."
          onselect={(option) => {
            formTargetDisplay = option.sublabel
              ? `${option.label} (${option.sublabel})`
              : option.label;
          }}
        />
        {#if isEdge(formKind)}
          <button type="button" class="toggle-btn" onclick={() => (formUseLabel = true)}>
            Machine not in the catalog, or several machines? Describe it instead
          </button>
        {/if}
      {/if}

      {#if isEdge(formKind)}
        <div class="form-field">
          <label class="form-field">
            <span class="field-label">License status</span>
            <select bind:value={formLicense}>
              {#each LICENSE_OPTIONS as option (option.value)}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
          </label>
          <span class="field-hint">Only mark licensed or unlicensed if a source says so.</span>
        </div>
        <p class="preview" aria-live="polite">
          {relationshipLead(formKind, formLicense)}
          {formUseLabel ? formLabel || '…' : formTargetDisplay || '…'}
        </p>
      {/if}

      {#if formError}
        <p class="row-error" role="alert">{formError}</p>
      {/if}

      <div class="form-actions">
        <button type="button" class="back-btn" onclick={() => (view = 'list')}>Cancel</button>
        <button type="button" class="commit-btn" onclick={commitForm}>
          {editingKey === null ? 'Add' : 'Update'}
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .related-models-editor {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .empty {
    color: var(--color-text-muted);
    margin: 0;
  }

  .row-text {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: inherit;
    font: inherit;
    text-align: left;
  }

  .row-text:hover {
    text-decoration: underline;
  }

  .row-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: var(--size-1) 0 0;
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

  .add-btn,
  .back-btn {
    background: none;
    border: 1px dashed var(--color-border-soft);
    border-radius: var(--radius-1);
    padding: var(--size-2) var(--size-3);
    cursor: pointer;
    color: var(--color-text-muted);
  }

  .add-btn {
    width: 100%;
  }

  .add-btn:hover,
  .back-btn:hover {
    border-color: var(--color-text-muted);
  }

  .picker-heading {
    margin: 0;
    font-size: var(--font-size-0);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-text-muted);
  }

  .kind-cards {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .kind-card {
    text-align: left;
    background: none;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-1);
    padding: var(--size-3);
    cursor: pointer;
    color: inherit;
    font: inherit;
  }

  .kind-card:hover:not(:disabled) {
    border-color: var(--color-text-muted);
  }

  .kind-card:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .kind-name {
    font-weight: 700;
    margin-right: var(--size-1);
  }

  .kind-example,
  .kind-note {
    font-style: italic;
    color: var(--color-text-muted);
    margin-left: var(--size-1);
  }

  .edge-form {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .form-field {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .field-label {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .field-hint {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    font-style: italic;
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

  .preview {
    margin: 0;
    padding: var(--size-2) var(--size-3);
    border-left: 3px solid var(--color-border-soft);
    color: var(--color-text-muted);
    font-style: italic;
  }

  .form-actions {
    display: flex;
    justify-content: space-between;
    gap: var(--size-2);
  }

  .commit-btn {
    background: none;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-1);
    padding: var(--size-2) var(--size-3);
    cursor: pointer;
    color: inherit;
  }

  .commit-btn:hover {
    border-color: var(--color-text-muted);
  }
</style>
