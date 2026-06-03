<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { auth } from '$lib/auth.svelte';
  import MetaTags from '$lib/components/layout/page/head/MetaTags.svelte';
  import { metaDescriptionFor } from '$lib/components/layout/page/head/meta-tags';
  import JsonLd from '$lib/components/layout/page/head/JsonLd.svelte';
  import ExternalLinksSidebarSection from '$lib/components/pages/record/detail/ExternalLinksSidebarSection.svelte';
  import { externalLinks } from '$lib/entities/external-links';
  import { model as modelInfo } from '$lib/entities/model';
  import { title as titleInfo } from '$lib/entities/title';
  import ModelHierarchy from '$lib/components/pages/record/detail/ModelHierarchy.svelte';
  import ModelSpecsSidebar from '$lib/components/pages/record/detail/ModelSpecsSidebar.svelte';
  import PageActionBar from '$lib/components/layout/page/PageActionBar.svelte';
  import RecordDetailShell from '$lib/components/pages/record/detail/RecordDetailShell.svelte';
  import SectionEditorHost from '$lib/components/pages/record/edit/SectionEditorHost.svelte';
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarListItem from '$lib/components/layout/page/sidebar/SidebarListItem.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import TaxonomyLinkSidebarSection from '$lib/components/pages/record/detail/TaxonomyLinkSidebarSection.svelte';
  import NeedsReviewBanner from './_components/NeedsReviewBanner.svelte';
  import {
    getMenuItemAction,
    type EditSectionMenuItem,
  } from '$lib/components/layout/page/edit-section-menu';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { resolveDetailSubrouteMode } from '$lib/detail-subroute-mode';
  import { isFocusModePath } from '$lib/focus-mode';
  import { setEntityContext } from '$lib/entity-context';
  import {
    combinedSectionsFor,
    type CombinedSectionKey,
  } from '$lib/components/pages/record/edit/editors/combined-edit-sections';
  import { modelHasTitleOwnedIdentity } from '$lib/catalog-rules';
  import { titleAreaEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import type { ModelEditSectionKey } from '$lib/components/pages/record/edit/editors/entity/model/model-edit-sections';
  import type { TitleEditSectionKey } from '$lib/components/pages/record/edit/editors/entity/title/title-edit-sections';
  import MediaEditor from '$lib/components/pages/record/edit/editors/MediaEditor.svelte';
  import ModelEditorSwitch from '$lib/components/pages/record/edit/editors/entity/model/ModelEditorSwitch.svelte';
  import TitleEditorSwitch from './edit/TitleEditorSwitch.svelte';

  let { data, children } = $props();
  let title = $derived(data.profile);
  let md = $derived(title.model_detail);
  // Model identities (IPDB/Pinside) plus the Title's own (Fandom): one source of
  // truth shared with the JSON-LD and the mobile accordion.
  let externalSiteLinks = $derived([
    ...(md ? externalLinks(md, modelInfo) : []),
    ...externalLinks(title, titleInfo),
  ]);
  let specs = $derived(title.agreed_specs);
  let slug = $derived(page.params.slug);

  $effect(() => {
    auth.load();
  });

  let mode = $derived(resolveDetailSubrouteMode(page.url.pathname));
  let isDetail = $derived(mode === 'detail');
  let isFocusMode = $derived(isFocusModePath(page.url.pathname));

  setEntityContext({
    get name() {
      return title.name;
    },
    get detailHref() {
      return resolve(`/titles/${slug}`);
    },
  });

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived(isMobileFlag.current);

  let metaDescription = $derived.by(() => {
    const parts = [title.name];
    if (md?.year) parts.push(`a ${md.year} pinball machine`);
    else parts.push('pinball title');
    if (md?.manufacturer) parts.push(`by ${md.manufacturer.name}`);
    return metaDescriptionFor(title, parts.join(' — '));
  });
  let heroImage = $derived(md ? md.hero_image_url : title.hero_image_url);

  let metaItems = $derived.by(() => {
    if (!md) return [];
    const items: Array<{ text: string; href?: string }> = [];
    if (md.manufacturer) {
      items.push({
        text: md.manufacturer.name,
        href: resolve(`/manufacturers/${md.manufacturer.public_id}`),
      });
    }
    if (md.year) {
      const yearText = md.month
        ? `${new Date(md.year, md.month - 1).toLocaleString('en', { month: 'long' })} ${md.year}`
        : `${md.year}`;
      items.push({ text: yearText });
    }
    return items;
  });

  // --- Combined-menu edit state ---

  let sections = $derived(combinedSectionsFor(!!md));
  let editing = $state<CombinedSectionKey | null>(null);
  let syncEnabled = $derived(!isMobile && !isFocusMode);
  // Tracks the last URL-derived edit section so local modal state doesn't immediately write it back.
  let lastUrlEditing = $state<CombinedSectionKey | null>(null);

  function updateEditQuery(nextEditing: CombinedSectionKey | null) {
    const current = page.url.searchParams.get('edit') ?? null;
    const desired = nextEditing ?? null;
    if (current === desired) return;
    const url = new URL(page.url);
    if (desired) url.searchParams.set('edit', desired);
    else url.searchParams.delete('edit');
    goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
  }

  function resolveEditingFromUrl(): CombinedSectionKey | null {
    if (!syncEnabled) return null;
    const value = page.url.searchParams.get('edit');
    if (!value) return null;
    const matched = sections.find((s) => s.key === value);
    return matched?.key ?? null;
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

  let switcherItems: EditSectionMenuItem[] = $derived([
    ...sections.map((s): EditSectionMenuItem => {
      if (!isMobile) {
        return { key: s.key, label: s.menuLabel, onclick: () => (editing = s.key) };
      }
      if (s.tier === 'title') {
        return {
          key: s.key,
          label: s.menuLabel,
          href: resolve(`/titles/${slug}/edit/${s.segment}`),
        };
      }
      // combinedSectionsFor only emits model-tier entries when md exists.
      if (!md) throw new Error('unreachable: model-tier section without model_detail');
      // The model edit route reads the model's title_models count to decide
      // whether BasicsEditor renders in slim mode — no entry-point signaling
      // needed here.
      return {
        key: s.key,
        label: s.menuLabel,
        href: resolve(`/models/${md.slug}/edit/${s.segment}`),
      };
    }),
    // "Create Model" is appended per the Record Create & Delete spec.
    // It's a navigation action (not a section editor), so it carries only
    // an `href`; auth gating happens via `editSectionsForBar` below, which
    // drops the whole menu when anonymous.
    {
      key: 'create-model',
      label: 'Create Model',
      href: resolve(`/titles/${slug}/models/new`),
    },
    // "Delete Title" is the last item in the menu (destructive action).
    // Navigates to a focus-mode confirmation page; auth gating rides
    // on editSectionsForBar.
    {
      key: 'delete-title',
      label: 'Delete Title',
      href: resolve(`/titles/${slug}/delete`),
      separatorBefore: true,
    },
  ]);

  let editSectionsForBar = $derived(auth.isAuthenticated ? switcherItems : undefined);

  // On single-Model Titles the Model's detail URL redirects to the Title,
  // so the Model's audit subroutes are otherwise unreachable from the UI —
  // surface them here alongside the Title's. See docs/SingleModelTitles.md.
  let historyMenu: EditSectionMenuItem[] | undefined = $derived(
    md
      ? [
          {
            key: 'title',
            label: 'Title History',
            href: resolve(`/titles/${slug}/edit-history`),
          },
          {
            key: 'model',
            label: 'Model History',
            href: resolve(`/models/${md.slug}/edit-history`),
          },
        ]
      : undefined,
  );
  let sourcesMenu: EditSectionMenuItem[] | undefined = $derived(
    md
      ? [
          {
            key: 'title',
            label: 'Title Sources',
            href: resolve(`/titles/${slug}/sources`),
          },
          {
            key: 'model',
            label: 'Model Sources',
            href: resolve(`/models/${md.slug}/sources`),
          },
        ]
      : undefined,
  );

  function editAction(key: CombinedSectionKey): (() => void) | undefined {
    if (!auth.isAuthenticated) return undefined;
    return getMenuItemAction(switcherItems, key, (href) => goto(href));
  }

  titleAreaEditActionContext.set(editAction);
</script>

<MetaTags
  title={title.name}
  description={metaDescription}
  url={page.url.href}
  image={heroImage}
  imageAlt={heroImage ? `${title.name} pinball machine` : undefined}
/>

{#if isDetail && data.jsonLd}
  <JsonLd data={data.jsonLd} />
{/if}

{#if isFocusMode}
  {@render children()}
{:else}
  {#if title.needs_review}
    <NeedsReviewBanner notes={title.needs_review_notes} links={title.review_links} />
  {/if}

  {#snippet actionBar()}
    <PageActionBar
      detailHref={isDetail ? undefined : resolve(`/titles/${slug}`)}
      editSections={editSectionsForBar}
      historyHref={resolve(`/titles/${slug}/edit-history`)}
      sourcesHref={resolve(`/titles/${slug}/sources`)}
      {historyMenu}
      {sourcesMenu}
    />
  {/snippet}

  {#snippet main()}
    {@render children()}
  {/snippet}

  {#snippet sidebar()}
    {#if md}
      <SidebarSection heading="Specifications">
        <ModelSpecsSidebar model={md} />
      </SidebarSection>

      {#if md.variants.length > 0}
        <SidebarSection heading="Variants">
          <SidebarList>
            {#each md.variants as variant (variant.public_id)}
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

      <ExternalLinksSidebarSection
        links={externalSiteLinks}
        note="See this title on other sites:"
        onEdit={editAction('model:external-data')}
      />
    {:else}
      {#if specs.technology_generation || specs.display_type || specs.player_count || specs.system || specs.cabinet || specs.game_format || specs.display_subtype || specs.production_quantity || (specs.themes && specs.themes.length > 0) || title.abbreviations.length > 0}
        <SidebarSection heading="Specifications">
          <dl>
            {#if specs.technology_generation}
              <dt>Generation</dt>
              <dd>
                <a
                  href={resolve(`/technology-generations/${specs.technology_generation.public_id}`)}
                  >{specs.technology_generation.name}</a
                >
              </dd>
            {/if}
            {#if specs.display_type}
              <dt>Display Type</dt>
              <dd>
                <a href={resolve(`/display-types/${specs.display_type.public_id}`)}
                  >{specs.display_type.name}</a
                >
              </dd>
            {/if}
            {#if specs.player_count}
              <dt>Players</dt>
              <dd>{specs.player_count}</dd>
            {/if}
            {#if specs.flipper_count}
              <dt>Flippers</dt>
              <dd>{specs.flipper_count}</dd>
            {/if}
            {#if specs.production_quantity}
              <dt>Units Made</dt>
              <dd>{specs.production_quantity}</dd>
            {/if}
            {#if specs.system}
              <dt>System</dt>
              <dd>
                <a href={resolve(`/systems/${specs.system.public_id}`)}>{specs.system.name}</a>
              </dd>
            {/if}
            {#if specs.themes && specs.themes.length > 0}
              <dt>Themes</dt>
              <dd>
                {#each specs.themes as theme, i (theme.public_id)}
                  {#if i > 0},{/if}
                  <a href={resolve(`/themes/${theme.public_id}`)}>{theme.name}</a>
                {/each}
              </dd>
            {/if}
            {#if specs.gameplay_features && specs.gameplay_features.length > 0}
              <dt>Features</dt>
              <dd>
                {#each specs.gameplay_features as feature, i (feature.public_id)}
                  {#if i > 0},{/if}
                  <a href={resolve(`/gameplay-features/${feature.public_id}`)}>{feature.name}</a
                  >{#if feature.count}&nbsp;({feature.count}){/if}
                {/each}
              </dd>
            {/if}
            {#if specs.reward_types && specs.reward_types.length > 0}
              <dt>Reward Types</dt>
              <dd>
                {#each specs.reward_types as rt, i (rt.public_id)}
                  {#if i > 0},{/if}
                  <a href={resolve(`/reward-types/${rt.public_id}`)}>{rt.name}</a>
                {/each}
              </dd>
            {/if}
            {#if title.abbreviations.length > 0}
              <dt>Abbrs</dt>
              <dd>{title.abbreviations.join(', ')}</dd>
            {/if}
            {#if specs.cabinet}
              <dt>Cabinet</dt>
              <dd>
                <a href={resolve(`/cabinets/${specs.cabinet.public_id}`)}>{specs.cabinet.name}</a>
              </dd>
            {/if}
            {#if specs.game_format}
              <dt>Format</dt>
              <dd>
                <a href={resolve(`/game-formats/${specs.game_format.public_id}`)}
                  >{specs.game_format.name}</a
                >
              </dd>
            {/if}
            {#if specs.display_subtype}
              <dt>Display</dt>
              <dd>
                <a href={resolve(`/display-subtypes/${specs.display_subtype.public_id}`)}
                  >{specs.display_subtype.name}</a
                >
              </dd>
            {/if}
          </dl>
        </SidebarSection>
      {/if}

      <TaxonomyLinkSidebarSection
        heading="Franchise"
        basePath="/franchises"
        item={title.franchise}
        onEdit={editAction('title:franchise')}
      />
      <TaxonomyLinkSidebarSection
        heading="Series"
        basePath="/series"
        item={title.series}
        onEdit={editAction('title:franchise')}
      />

      {#if title.machines.length > 0}
        <ModelHierarchy models={title.machines} />
      {/if}
    {/if}
  {/snippet}

  <RecordDetailShell
    name={title.name}
    heroImageUrl={md ? md.hero_image_url : title.hero_image_url}
    heroImageAlt="{title.name} backglass"
    {metaItems}
    sidebarDesktopOnly={isDetail}
    {actionBar}
    {main}
    {sidebar}
  />

  <SectionEditorHost bind:editingKey={editing} {sections} {switcherItems}>
    {#snippet editor(key, { ref, onsaved, onerror, ondirtychange })}
      {#if key.startsWith('title:')}
        <TitleEditorSwitch
          sectionKey={key.slice('title:'.length) as TitleEditSectionKey}
          initialData={title}
          slug={title.slug}
          bind:editorRef={ref.current}
          {onsaved}
          {onerror}
          {ondirtychange}
        />
      {:else if md}
        <ModelEditorSwitch
          sectionKey={key.slice('model:'.length) as ModelEditSectionKey}
          initialData={md}
          slug={md.slug}
          slim={modelHasTitleOwnedIdentity(md)}
          bind:editorRef={ref.current}
          {onsaved}
          {onerror}
          {ondirtychange}
        />
      {/if}
    {/snippet}

    {#snippet immediateEditor()}
      {#if md}
        <MediaEditor entityType="model" slug={md.slug} media={md.uploaded_media} />
      {/if}
    {/snippet}
  </SectionEditorHost>
{/if}

<style>
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0 var(--size-3);
    align-items: baseline;
  }

  dt,
  dd {
    font-size: var(--font-size-0);
    margin: 0;
    padding: 2px 0;
  }

  dt {
    color: var(--color-text-muted);
    font-weight: 500;
  }

  dd {
    color: var(--color-text);
  }

  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }
</style>
