<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { auth } from '$lib/auth.svelte';
  import MetaTags from '$lib/components/MetaTags.svelte';
  import JsonLd from '$lib/components/JsonLd.svelte';
  import ExternalLinksSidebarSection from '$lib/components/ExternalLinksSidebarSection.svelte';
  import ModelHierarchy from '$lib/components/ModelHierarchy.svelte';
  import ModelSpecsSidebar from '$lib/components/ModelSpecsSidebar.svelte';
  import PageActionBar from '$lib/components/PageActionBar.svelte';
  import RatingsSidebarSection from '$lib/components/RatingsSidebarSection.svelte';
  import RecordDetailShell from '$lib/components/RecordDetailShell.svelte';
  import SectionEditorHost from '$lib/components/SectionEditorHost.svelte';
  import SidebarList from '$lib/components/SidebarList.svelte';
  import SidebarListItem from '$lib/components/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/SidebarSection.svelte';
  import TaxonomyLinkSidebarSection from '$lib/components/TaxonomyLinkSidebarSection.svelte';
  import { getMenuItemAction, type EditSectionMenuItem } from '$lib/components/edit-section-menu';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { modelHasTitleOwnedIdentity } from '$lib/catalog-rules';
  import { resolveDetailSubrouteMode } from '$lib/detail-subroute-mode';
  import { isFocusModePath } from '$lib/focus-mode';
  import { setEntityContext } from '$lib/entity-context';
  import { modelEditActionContext } from '$lib/components/editors/edit-action-context';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import MediaEditor from '$lib/components/editors/MediaEditor.svelte';
  import ModelEditorSwitch from './edit/ModelEditorSwitch.svelte';

  let { data, children } = $props();
  let model = $derived(data.profile);
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
    if (model.description?.text) return model.description.text;
    const parts = [model.name];
    if (model.year) parts.push(`a ${model.year} pinball machine`);
    else parts.push('pinball machine');
    if (model.manufacturer) parts.push(`by ${model.manufacturer.name}`);
    return parts.join(' — ');
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
  } from '$lib/components/editors/model-edit-sections';

  // The dedicated edit route and this reader-level editor must agree on which
  // sections are writable — otherwise a title-owned model would still expose a
  // model-side Name editor from the reader menu or the ?edit=name URL,
  // producing claim writes against the Model row instead of the Title row.
  let availableSections = $derived(modelSectionsFor(modelHasTitleOwnedIdentity(model)));

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
  title={model.name}
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

    <RatingsSidebarSection ipdbRating={model.ipdb_rating} pinsideRating={model.pinside_rating} />

    <TaxonomyLinkSidebarSection heading="Franchise" basePath="/franchises" item={model.franchise} />
    <TaxonomyLinkSidebarSection heading="Series" basePath="/series" item={model.series} />

    {#if model.title}
      <SidebarSection heading="Parent Title">
        <SidebarList>
          <SidebarListItem>
            <a href={resolve(`/titles/${model.title.public_id}`)}>{model.title.name}</a>
          </SidebarListItem>
        </SidebarList>
      </SidebarSection>
    {/if}

    {#if model.variants.length > 0}
      <SidebarSection
        heading="Variants of this Model"
        note="These play identically, differing only cosmetically:"
      >
        <SidebarList>
          {#each model.variants as variant (variant.public_id)}
            <SidebarListItem>
              <a href={resolve(`/models/${variant.public_id}`)}>{variant.name}</a>
              {#if variant.year}
                <span class="muted">{variant.year}</span>
              {/if}
            </SidebarListItem>
          {/each}
        </SidebarList>
      </SidebarSection>
    {/if}

    {#if model.variant_of}
      <SidebarSection heading="Parent Model">
        <SidebarList>
          <SidebarListItem>
            <a href={resolve(`/models/${model.variant_of.public_id}`)}>{model.variant_of.name}</a>
            {#if model.variant_of.year}
              <span class="muted">{model.variant_of.year}</span>
            {/if}
          </SidebarListItem>
        </SidebarList>
      </SidebarSection>
    {/if}

    {#if model.variant_siblings && model.variant_siblings.length > 0}
      <SidebarSection heading="Other Variants">
        <SidebarList>
          {#each model.variant_siblings as sibling (sibling.public_id)}
            <SidebarListItem>
              <a href={resolve(`/models/${sibling.public_id}`)}>{sibling.name}</a>
              {#if sibling.year}
                <span class="muted">{sibling.year}</span>
              {/if}
            </SidebarListItem>
          {/each}
        </SidebarList>
      </SidebarSection>
    {/if}

    {#if model.converted_from}
      <SidebarSection heading="Converted From" note="This game was rebuilt from the hardware of:">
        <SidebarList>
          <SidebarListItem>
            <a href={resolve(`/models/${model.converted_from.public_id}`)}
              >{model.converted_from.name}</a
            >
            {#if model.converted_from.year}
              <span class="muted">{model.converted_from.year}</span>
            {/if}
          </SidebarListItem>
        </SidebarList>
      </SidebarSection>
    {/if}

    {#if model.conversions && model.conversions.length > 0}
      <SidebarSection
        heading="Conversions"
        note="Different games rebuilt from this machine's hardware:"
      >
        <SidebarList>
          {#each model.conversions as conversion (conversion.public_id)}
            <SidebarListItem>
              <a href={resolve(`/models/${conversion.public_id}`)}>{conversion.name}</a>
              {#if conversion.year}
                <span class="muted">{conversion.year}</span>
              {/if}
            </SidebarListItem>
          {/each}
        </SidebarList>
      </SidebarSection>
    {/if}

    {#if model.remake_of}
      <SidebarSection heading="Remake Of" note="This game is a remake of:">
        <SidebarList>
          <SidebarListItem>
            <a href={resolve(`/models/${model.remake_of.public_id}`)}>{model.remake_of.name}</a>
            {#if model.remake_of.year}
              <span class="muted">{model.remake_of.year}</span>
            {/if}
          </SidebarListItem>
        </SidebarList>
      </SidebarSection>
    {/if}

    {#if model.remakes && model.remakes.length > 0}
      <SidebarSection heading="Remakes" note="Later remakes of this machine:">
        <SidebarList>
          {#each model.remakes as remake (remake.public_id)}
            <SidebarListItem>
              <a href={resolve(`/models/${remake.public_id}`)}>{remake.name}</a>
              {#if remake.year}
                <span class="muted">{remake.year}</span>
              {/if}
            </SidebarListItem>
          {/each}
        </SidebarList>
      </SidebarSection>
    {/if}

    <ModelHierarchy
      models={model.title_models}
      heading="Other Models In Title"
      excludeSlug={model.variant_of?.public_id ?? model.slug}
    />

    <ExternalLinksSidebarSection
      ipdbId={model.ipdb_id}
      opdbId={model.opdb_id}
      pinsideId={model.pinside_id}
      note="See this model on other sites:"
    />
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
    {#snippet editor(key, { ref, onsaved, onerror, ondirtychange })}
      <ModelEditorSwitch
        sectionKey={key}
        initialData={model}
        slug={model.slug}
        slim={modelHasTitleOwnedIdentity(model)}
        bind:editorRef={ref.current}
        {onsaved}
        {onerror}
        {ondirtychange}
      />
    {/snippet}

    {#snippet immediateEditor()}
      <MediaEditor entityType="model" slug={model.slug} media={model.uploaded_media} />
    {/snippet}
  </SectionEditorHost>
{/if}

<style>
  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }
</style>
