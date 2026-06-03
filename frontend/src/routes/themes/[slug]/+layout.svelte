<script lang="ts">
  import client from '$lib/api/client';
  import TaxonomyDetailBaseLayout from '$lib/components/pages/record/detail/TaxonomyDetailBaseLayout.svelte';
  import HierarchicalTaxonomySidebar from '$lib/components/pages/record/detail/HierarchicalTaxonomySidebar.svelte';
  import HierarchicalTaxonomyEditorSwitch from '$lib/components/editors/HierarchicalTaxonomyEditorSwitch.svelte';
  import { hierarchicalTaxonomyEditActionContext } from '$lib/components/editors/edit-action-context';
  import {
    HIERARCHICAL_TAXONOMY_EDIT_SECTIONS,
    type HierarchicalTaxonomyEditSectionKey,
  } from '$lib/components/editors/hierarchical-taxonomy-edit-sections';
  import { listingMeta } from '$lib/entities/schema-org';

  let { data, children } = $props();
  let theme = $derived(data.profile);

  const BASE_PATH = '/themes';

  const sections = HIERARCHICAL_TAXONOMY_EDIT_SECTIONS.map((section) =>
    section.key === 'parents' ? { ...section, label: 'Parent Themes' } : section,
  );

  // Unlike gameplay-features, themes has historically shown aliases verbatim
  // (no near-duplicate filter against the canonical name). Preserve that.
  let aliases = $derived(theme.aliases ?? []);
  let childHeading = 'Sub-themes';

  async function loadParentOptions() {
    const { data: themes } = await client.GET('/api/themes/all/');
    if (!themes) return [];
    return themes.map((t) => ({
      slug: t.slug,
      label: t.name,
    }));
  }
</script>

<TaxonomyDetailBaseLayout
  profile={theme}
  jsonLd={data.jsonLd}
  parentLabel={listingMeta('theme').breadcrumb}
  basePath={BASE_PATH}
  {sections}
  {aliases}
  editActionContext={hierarchicalTaxonomyEditActionContext}
  deleteHref={`${BASE_PATH}/${theme.slug}/delete`}
>
  {#snippet sidebar()}
    <HierarchicalTaxonomySidebar
      basePath={BASE_PATH}
      parents={theme.parents ?? []}
      children={theme.children ?? []}
      aliases={[]}
      parentHeading="Parent themes"
      {childHeading}
    />
  {/snippet}

  {#snippet editor(
    key: HierarchicalTaxonomyEditSectionKey,
    { ref, onsaved, onerror, ondirtychange },
  )}
    <HierarchicalTaxonomyEditorSwitch
      sectionKey={key}
      initialData={theme}
      slug={theme.slug}
      claimsPath={'/api/themes/{public_id}/claims/'}
      parentOptionsLoader={loadParentOptions}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
      {ondirtychange}
    />
  {/snippet}

  {@render children()}
</TaxonomyDetailBaseLayout>
