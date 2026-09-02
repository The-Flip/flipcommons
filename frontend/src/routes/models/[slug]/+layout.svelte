<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { auth } from '$lib/auth.svelte';
  import MetaTags from '$lib/components/layout/page/head/MetaTags.svelte';
  import { entityPageTitle, metaDescriptionFor } from '$lib/components/layout/page/head/meta-tags';
  import JsonLd from '$lib/components/layout/page/head/JsonLd.svelte';
  import ExternalLinksSidebarSection from '$lib/components/pages/record/detail/ExternalLinksSidebarSection.svelte';
  import { externalLinks } from '$lib/entities/external-links';
  import { UNKNOWN_MANUFACTURER_LABEL } from '$lib/entities/manufacturer';
  import { model as modelInfo } from '$lib/entities/model';
  import { showsProductionStatus } from '$lib/entities/production-status';
  import ModelHierarchy from '$lib/components/pages/record/detail/ModelHierarchy.svelte';
  import ModelLineageSidebarSections from '$lib/components/pages/record/detail/ModelLineageSidebarSections.svelte';
  import ModelSpecsSidebar from '$lib/components/pages/record/detail/ModelSpecsSidebar.svelte';
  import PageActionBar from '$lib/components/layout/page/PageActionBar.svelte';
  import RecordDetailShell from '$lib/components/pages/record/detail/RecordDetailShell.svelte';
  import SectionEditorHost from '$lib/components/pages/record/edit/SectionEditorHost.svelte';
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarListItem from '$lib/components/layout/page/sidebar/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import TaxonomyLinkSidebarSection from '$lib/components/pages/record/detail/TaxonomyLinkSidebarSection.svelte';
  import {
    getMenuItemAction,
    type EditSectionMenuItem,
  } from '$lib/components/layout/page/edit-section-menu';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { modelHasTitleOwnedIdentity } from '$lib/catalog-rules';
  import { resolveDetailSubrouteMode } from '$lib/detail-subroute-mode';
  import { isFocusModePath } from '$lib/focus-mode';
  import { setEntityContext } from '$lib/entity-context';
  import { modelEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import MediaEditor from '$lib/components/pages/record/edit/editors/MediaEditor.svelte';
  import ModelEditorSwitch from '$lib/components/pages/record/edit/editors/entity/model/ModelEditorSwitch.svelte';

  let { data, children } = $props();
  let model = $derived(data.profile);
  let externalSiteLinks = $derived(externalLinks(model, modelInfo));
  let slug = $derived(page.params.slug);

  $effect(() => {
    auth.load();
  });

  let mode = $derived(resolveDetailSubrouteMode(page.url.pathname));
  // isDetail still drives (a) the "Reader" back-link in PageActionBar,
  // and (b) whether the sidebar is desktop-only — on sub-routes the sidebar
  // is shown on mobile too because the main column no longer duplicates it.
  let isDetail = $derived(mode === 'detail');
  let isFocusMode = $derived(isFocusModePath(page.url.pathname));

  setEntityContext({
    get name() {
      return model.name;
    },
    get detailHref() {
      return resolve(`/models/${slug}`);
    },
  });

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived(isMobileFlag.current);

  let metaDescription = $derived.by(() => {
    const parts = [model.name];
    if (model.year) parts.push(`a ${model.year} pinball machine`);
    else parts.push('pinball machine');
    if (model.manufacturer) parts.push(`by ${model.manufacturer.name}`);
    return metaDescriptionFor(model, parts.join(' — '));
  });

  let parentLink = $derived(
    model.title
      ? { text: model.title.name, href: resolve(`/titles/${model.title.public_id}`) }
      : null,
  );

  let metaItems = $derived.by(() => {
    const items: Array<{ text: string; href?: string }> = [];
    if (model.manufacturer) {
      items.push({
        text: model.manufacturer.name,
        href: resolve(`/manufacturers/${model.manufacturer.public_id}`),
      });
    } else {
      items.push({ text: UNKNOWN_MANUFACTURER_LABEL });
    }
    if (model.year) {
      const yearText = model.month
        ? `${new Date(model.year, model.month - 1).toLocaleString('en', { month: 'long' })} ${model.year}`
        : `${model.year}`;
      items.push({ text: yearText });
    }
    return items;
  });

  // --- Section editing state ---

  import {
    findSectionByKey,
    findSectionBySegment,
    modelSectionsFor,
    type ModelEditSectionKey,
  } from '$lib/components/pages/record/edit/editors/entity/model/model-edit-sections';

  // The dedicated edit route and this reader-level editor must agree on which
  // sections are writable — otherwise a title-owned model would still expose a
  // model-side Name editor from the reader menu or the ?edit=name URL,
  // producing claim writes against the Model row instead of the Title row.
  let availableSections = $derived(modelSectionsFor(modelHasTitleOwnedIdentity(model)));

  let metaTitle = $derived(
    entityPageTitle(model.name, page.url.pathname, `/models/${slug}`, availableSections),
  );

  let editing = $state<ModelEditSectionKey | null>(null);
  let syncEnabled = $derived(!isMobile && !isFocusMode);
  // Tracks the last URL-derived edit section so local modal state doesn't immediately write it back.
  let lastUrlEditing = $state<ModelEditSectionKey | null>(null);

  function updateEditQuery(nextEditing: ModelEditSectionKey | null) {
    const current = page.url.searchParams.get('edit') ?? null;
    const desired = nextEditing ? (findSectionByKey(nextEditing)?.segment ?? null) : null;
    if (current === desired) return;
    const url = new URL(page.url);
    if (desired) url.searchParams.set('edit', desired);
    else url.searchParams.delete('edit');
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function resolveEditingFromUrl(): ModelEditSectionKey | null {
    if (!syncEnabled) return null;
    const section = page.url.searchParams.get('edit');
    const matched = section ? findSectionBySegment(section) : undefined;
    if (!matched) return null;
    // Reject sections that are filtered out for this model (e.g. `?edit=name`
    // on a title-owned model) so the reader can't bypass the menu filter.
    if (!availableSections.some((s) => s.key === matched.key)) return null;
    return matched.key;
  }

  $effect(() => {
    const nextEditing = resolveEditingFromUrl();
    lastUrlEditing = nextEditing;
    editing = nextEditing;
  });

  $effect(() => {
    if (!syncEnabled) return;
    if (editing === lastUrlEditing) return;
    lastUrlEditing = editing;
    updateEditQuery(editing);
  });

  let editSections: EditSectionMenuItem[] = $derived([
    ...availableSections.map((section) =>
      isMobile
        ? {
            key: section.key,
            label: section.label,
            href: resolve(`/models/${slug}/edit/${section.segment}`),
          }
        : {
            key: section.key,
            label: section.label,
            onclick: () => (editing = section.key),
          },
    ),
    // "Delete Model" is the last item in the menu (destructive action).
    // Navigates to a focus-mode confirmation page; the whole menu is
    // hidden for anonymous users via the `auth.isAuthenticated` check
    // on PageActionBar's `editSections` prop below.
    {
      key: 'delete-model',
      label: 'Delete Model',
      href: resolve(`/models/${slug}/delete`),
      separatorBefore: true,
    },
  ]);

  function editAction(sectionKey: ModelEditSectionKey): (() => void) | undefined {
    if (!auth.isAuthenticated) return undefined;
    return getMenuItemAction(editSections, sectionKey, (href) => goto(href));
  }

  // Expose editAction to the detail page so accordion [edit] links can reach the
  // layout's modal host (desktop) or nav (mobile) without the page knowing how.
  modelEditActionContext.set(editAction);

  // Desktop sidebar shows Franchise/Series as their own sections, so the Features
  // sidebar should hide when *only* franchise/series would appear.
  let hasFeaturesExcludingFranchiseSeries = $derived(
    showsProductionStatus(model.production_status) ||
      !!model.game_format ||
      !!model.cabinet ||
      (model.reward_types?.length ?? 0) > 0 ||
      model.themes.length > 0 ||
      !!model.production_quantity ||
      !!model.player_count ||
      !!model.flipper_count ||
      model.gameplay_features.length > 0 ||
      model.variant_features.length > 0,
  );
  let hasTechnology = $derived(
    !!model.technology_generation ||
      !!model.technology_subgeneration ||
      !!model.display_type ||
      !!model.display_subtype ||
      !!model.system,
  );
</script>

<MetaTags
  title={metaTitle}
  description={metaDescription}
  url={page.url.href}
  image={model.hero_image_url}
  imageAlt={model.hero_image_url ? `${model.name} pinball machine` : undefined}
/>

{#if isDetail && data.jsonLd}
  <JsonLd data={data.jsonLd} />
{/if}

{#if isFocusMode}
  {@render children()}
{:else}
  {#snippet actionBar()}
    <PageActionBar
      detailHref={isDetail ? undefined : resolve(`/models/${slug}`)}
      editSections={auth.isAuthenticated ? editSections : undefined}
      historyHref={resolve(`/models/${slug}/edit-history`)}
      sourcesHref={resolve(`/models/${slug}/sources`)}
    />
  {/snippet}

  {#snippet main()}
    {@render children()}
  {/snippet}

  {#snippet sidebar()}
    {#if hasTechnology}
      <SidebarSection heading="Technology" onEdit={editAction('technology')}>
        <ModelSpecsSidebar {model} section="technology" />
      </SidebarSection>
    {/if}

    {#if hasFeaturesExcludingFranchiseSeries}
      <SidebarSection heading="Features" onEdit={editAction('features')}>
        <ModelSpecsSidebar {model} section="features" showFranchiseSeries={false} />
      </SidebarSection>
    {/if}

    <TaxonomyLinkSidebarSection heading="Franchise" basePath="/franchises" item={model.franchise} />
    <TaxonomyLinkSidebarSection heading="Series" basePath="/series" item={model.series} />

    <SidebarSection heading="Parent Title">
      <SidebarList>
        <SidebarListItem>
          <a href={resolve(`/titles/${model.title.public_id}`)}>{model.title.name}</a>
        </SidebarListItem>
      </SidebarList>
    </SidebarSection>

    <ModelLineageSidebarSections {model} />

    <ModelHierarchy
      models={model.title_models}
      heading="Other Models In Title"
      excludeSlug={model.variant_of?.public_id ?? model.slug}
      subjectManufacturer={model.manufacturer?.name ?? null}
      subjectYear={model.year ?? null}
    />

    <ExternalLinksSidebarSection links={externalSiteLinks} note="See this model on other sites:" />
  {/snippet}

  <RecordDetailShell
    name={model.name}
    heroImageUrl={model.hero_image_url}
    heroImageAlt="{model.name} backglass"
    {parentLink}
    {metaItems}
    sidebarDesktopOnly={isDetail}
    {actionBar}
    {main}
    {sidebar}
  />

  <SectionEditorHost
    bind:editingKey={editing}
    sections={availableSections}
    switcherItems={editSections}
  >
    {#snippet editor(key, { ref, onsaved, onerror })}
      <ModelEditorSwitch
        sectionKey={key}
        initialData={model}
        slug={model.slug}
        slim={modelHasTitleOwnedIdentity(model)}
        bind:editorRef={ref.current}
        {onsaved}
        {onerror}
      />
    {/snippet}

    {#snippet immediateEditor()}
      <MediaEditor entityType="model" slug={model.slug} media={model.uploaded_media} />
    {/snippet}
  </SectionEditorHost>
{/if}
