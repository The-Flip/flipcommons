<script lang="ts">
  import type { Snippet } from 'svelte';
  import TaxonomyDetailBaseLayout from '$lib/components/TaxonomyDetailBaseLayout.svelte';
  import type { Crumb } from '$lib/components/Breadcrumb.svelte';
  import {
    SIMPLE_TAXONOMY_EDIT_SECTIONS,
    type SimpleTaxonomyEditSectionDef,
    type SimpleTaxonomyEditSectionKey,
  } from '$lib/components/editors/simple-taxonomy-edit-sections';
  import SimpleTaxonomyEditorSwitch from '$lib/components/editors/SimpleTaxonomyEditorSwitch.svelte';
  import type { SimpleTaxonomyClaimsPath } from '$lib/components/editors/save-claims-shared';
  import type { SimpleTaxonomyEditView } from '$lib/components/editors/simple-taxonomy-edit-types';

  let {
    profile,
    jsonLd,
    parentLabel,
    basePath,
    parentHref,
    breadcrumbs,
    claimsPath,
    deleteHref,
    createChild,
    sections: sectionsProp = SIMPLE_TAXONOMY_EDIT_SECTIONS,
    children,
  }: {
    profile: SimpleTaxonomyEditView;
    jsonLd?: Record<string, unknown>;
    parentLabel: string;
    basePath: string;
    parentHref?: string;
    /** Multi-level trail shown instead of the single `parentLabel` kicker. */
    breadcrumbs?: Crumb[];
    claimsPath: SimpleTaxonomyClaimsPath;
    deleteHref?: string;
    createChild?: { href: string; label: string };
    /** Override the default section list. Defaults to all 3 simple-taxonomy
     * sections; pass a subset to omit sections that don't apply. */
    sections?: SimpleTaxonomyEditSectionDef[];
    children: Snippet;
  } = $props();

  let sections = $derived(
    sectionsProp.map((section) => ({ ...section, usesSectionEditorForm: true })),
  );
</script>

<TaxonomyDetailBaseLayout
  {profile}
  {jsonLd}
  {parentLabel}
  {basePath}
  {parentHref}
  {breadcrumbs}
  {sections}
  {deleteHref}
  {createChild}
>
  {#snippet editor(key: SimpleTaxonomyEditSectionKey, { ref, onsaved, onerror, ondirtychange })}
    <SimpleTaxonomyEditorSwitch
      sectionKey={key}
      initialData={profile}
      slug={profile.slug}
      {claimsPath}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
      {ondirtychange}
    />
  {/snippet}
  {@render children()}
</TaxonomyDetailBaseLayout>
