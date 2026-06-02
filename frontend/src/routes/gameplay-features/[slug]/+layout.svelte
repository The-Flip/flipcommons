<script lang="ts">
  import client from '$lib/api/client';
  import TaxonomyDetailBaseLayout from '$lib/components/TaxonomyDetailBaseLayout.svelte';
  import HierarchicalTaxonomySidebar from '$lib/components/HierarchicalTaxonomySidebar.svelte';
  import MediaEditor from '$lib/components/editors/MediaEditor.svelte';
  import HierarchicalTaxonomyEditorSwitch from '$lib/components/editors/HierarchicalTaxonomyEditorSwitch.svelte';
  import { hierarchicalTaxonomyEditActionContext } from '$lib/components/editors/edit-action-context';
  import {
    HIERARCHICAL_TAXONOMY_EDIT_SECTIONS,
    MEDIA_SECTION,
    type HierarchicalTaxonomyEditSectionKey,
  } from '$lib/components/editors/hierarchical-taxonomy-edit-sections';
  import { displayAliasesFor } from '$lib/hierarchy-edit';

  let { data, children } = $props();
  let profile = $derived(data.profile);

  const BASE_PATH = '/gameplay-features';

  const sections = [
    ...HIERARCHICAL_TAXONOMY_EDIT_SECTIONS.map((section) =>
      section.key === 'parents' ? { ...section, label: 'Parent Features' } : section,
    ),
    MEDIA_SECTION,
  ];

  let displayAliases = $derived(displayAliasesFor(profile.name, profile.aliases ?? []));

  async function loadParentOptions() {
    const { data: features } = await client.GET('/api/gameplay-features/all/');
    if (!features) return [];
    return features.map((f) => ({
      slug: f.slug,
      label: f.name,
      count: f.title_count,
    }));
  }
</script>

<TaxonomyDetailBaseLayout
  {profile}
  jsonLd={data.jsonLd}
  parentLabel="Gameplay Features"
  basePath={BASE_PATH}
  {sections}
  editActionContext={hierarchicalTaxonomyEditActionContext}
  deleteHref={`${BASE_PATH}/${profile.slug}/delete`}
>
  {#snippet sidebar()}
    <HierarchicalTaxonomySidebar
      basePath={BASE_PATH}
      parents={profile.parents ?? []}
      children={profile.children ?? []}
      aliases={displayAliases}
      parentHeading="Type of"
      childHeading="Subtypes"
    />
  {/snippet}

  {#snippet editor(
    key: HierarchicalTaxonomyEditSectionKey,
    { ref, onsaved, onerror, ondirtychange },
  )}
    <HierarchicalTaxonomyEditorSwitch
      sectionKey={key}
      initialData={profile}
      slug={profile.slug}
      claimsPath={'/api/gameplay-features/{public_id}/claims/'}
      parentOptionsLoader={loadParentOptions}
      parentsLabel="This feature is a type of..."
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
      {ondirtychange}
    />
  {/snippet}

  {#snippet immediateEditor()}
    <MediaEditor
      entityType="gameplay-feature"
      slug={profile.slug}
      media={profile.uploaded_media ?? []}
    />
  {/snippet}

  {@render children()}
</TaxonomyDetailBaseLayout>
