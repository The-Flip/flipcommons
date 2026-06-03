<!--
  Kiosk editor. Loads one KioskConfig from the server, lets a superuser tweak
  page heading, idle timeout, and the ordered list of items, and PATCHes
  back. Items are sent as full replacement (the resource API drops + bulk-creates
  inside a transaction). Also hosts the "Delete Kiosk" and "Enter Kiosk Mode"
  controls for this config.

  Kiosks are identified by their integer primary key (e.g. "#7"); there is
  no admin label.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import client from '$lib/api/client';
  import { parseApiError } from '$lib/api/parse-api-error';
  import { resolve } from '$app/paths';
  import { normalizeText } from '$lib/utils';
  import { toast } from '$lib/toast/toast.svelte';
  import { matchesQuery } from '$lib/facet-engine';
  import {
    clearKioskCookies,
    getKioskConfigIdFromCookie,
    HOOK_MAX_LENGTH,
    setKioskCookies,
  } from '$lib/kiosk/config';
  import Breadcrumb from '$lib/components/Breadcrumb.svelte';
  import Button from '$lib/components/Button.svelte';
  import Page from '$lib/components/Page.svelte';
  import TwoColumnLayout from '$lib/components/TwoColumnLayout.svelte';
  import SidebarSection from '$lib/components/SidebarSection.svelte';
  import StatusMessage from '$lib/components/StatusMessage.svelte';
  import type { TitleListItemSchema } from '$lib/api/schema';

  let { data } = $props();
  // The editor seeds its mutable working state from data.config once on
  // mount; subsequent edits never re-import from `data`. The whole page
  // re-mounts on a different :id so we don't need data to be reactive
  // here.
  // svelte-ignore state_referenced_locally
  const config = data.config;
  // activeId comes from +page.server.ts (reads kioskConfigId cookie).
  // Local mutable copy so exitKioskMode() can clear it without a full
  // reload. Reading it server-side avoids an SSR/hydration flash.
  // svelte-ignore state_referenced_locally
  let activeId = $state<number | null>(data.activeId);
  let isActive = $derived(activeId === config.id);

  type EditorItem = { titleSlug: string; titleName: string; hook: string };

  let pageHeading = $state(config.page_heading);
  let idleSeconds = $state(config.idle_seconds);
  let items = $state<EditorItem[]>(
    config.items.map((i) => ({
      titleSlug: i.title.public_id,
      titleName: i.title.name,
      hook: i.hook,
    })),
  );

  let initialIdleSeconds = config.idle_seconds;

  let allTitles = $state<TitleListItemSchema[]>([]);
  let search = $state('');
  let saving = $state(false);
  let deleting = $state(false);
  let errorMessage = $state<string | null>(null);
  // savePending: a save was requested while another was in flight. Coalesces
  // multiple overlapping requests into exactly one trailing save with the
  // latest state.
  let savePending = $state(false);
  // saveStatus drives the "Saving…" / "Saved" indicator. Goes idle → saving
  // → saved (briefly) → idle. "saved" auto-clears on the next edit or after
  // a short delay.
  let saveStatus = $state<'idle' | 'saving' | 'saved'>('idle');
  let savedClearTimer: ReturnType<typeof setTimeout> | undefined;

  const idLabel = `#${config.id}`;

  // Build the current PATCH body. Used both as the actual request body
  // and (stringified) to compare against the last-saved snapshot — a blur
  // with no real changes shouldn't fire a no-op PATCH or flash the
  // "Saving / Saved" indicator.
  function buildBody() {
    return {
      page_heading: pageHeading.trim(),
      idle_seconds: idleSeconds,
      items: items.map((item, position) => ({
        title_slug: item.titleSlug,
        hook: item.hook.slice(0, HOOK_MAX_LENGTH),
        position,
      })),
    };
  }
  // Seed with the initial-loaded state so the first blur with no edits
  // is a no-op.
  let lastSavedPayload = JSON.stringify(buildBody());

  let configuredSlugs = $derived(new Set(items.map((i) => i.titleSlug)));
  let titleBySlug = $derived(new Map(allTitles.map((t) => [t.slug, t])));

  let searchResults = $derived.by(() => {
    const q = normalizeText(search);
    if (!q) return [];
    return allTitles
      .filter((t) => !configuredSlugs.has(t.slug))
      .filter((t) => matchesQuery(t, q))
      .slice(0, 12);
  });

  onMount(async () => {
    const res = await client.GET('/api/titles/all/');
    if (res.data) allTitles = res.data;
  });

  function addTitle(t: TitleListItemSchema) {
    items = [...items, { titleSlug: t.slug, titleName: t.name, hook: '' }];
    search = '';
    void save();
  }

  function removeAt(index: number) {
    items = items.filter((_, i) => i !== index);
    void save();
  }

  function moveUp(index: number) {
    if (index === 0) return;
    const next = [...items];
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    items = next;
    void save();
  }

  function moveDown(index: number) {
    if (index === items.length - 1) return;
    const next = [...items];
    [next[index + 1], next[index]] = [next[index], next[index + 1]];
    items = next;
    void save();
  }

  async function save() {
    if (saving) {
      // A save is already running; remember to fire one more after it
      // resolves with whatever the latest state is then.
      savePending = true;
      return;
    }

    // Front-line validation: <input type="number"> can yield NaN when the
    // browser accepts a paste or non-digit input. Catch that here so we
    // don't silently coerce to a default and persist the wrong value.
    if (!Number.isInteger(idleSeconds) || idleSeconds < 1) {
      errorMessage = 'Idle timeout must be a positive whole number of seconds.';
      saveStatus = 'idle';
      return;
    }

    // Skip no-op blurs: if nothing changed since the last save, don't
    // fire a PATCH and don't flip the "Saving / Saved" indicator.
    const body = buildBody();
    const payload = JSON.stringify(body);
    if (payload === lastSavedPayload) return;

    saving = true;
    saveStatus = 'saving';
    errorMessage = null;
    if (savedClearTimer !== undefined) clearTimeout(savedClearTimer);

    const { data: updated, error } = await client.PATCH('/api/kiosk/configs/{config_id}/', {
      params: { path: { config_id: config.id } },
      body,
    });
    saving = false;

    if (error || !updated) {
      const parsed = parseApiError(error);
      errorMessage = parsed.message;
      saveStatus = 'idle';
      // Drop any queued save: the user needs to react to the error before
      // we keep retrying with the same body.
      savePending = false;
      return;
    }

    // Refresh the local kioskIdleSeconds cookie if this device is the
    // active kiosk for the config we just edited and idle_seconds changed.
    if (
      updated.idle_seconds !== initialIdleSeconds &&
      getKioskConfigIdFromCookie() === updated.id
    ) {
      setKioskCookies(updated.id, updated.idle_seconds);
    }
    initialIdleSeconds = updated.idle_seconds;
    lastSavedPayload = payload;

    if (savePending) {
      // Edits arrived while we were in flight. Run exactly one trailing
      // save with the current state — no pause, no "Saved" flash.
      savePending = false;
      void save();
      return;
    }

    saveStatus = 'saved';
    savedClearTimer = setTimeout(() => {
      saveStatus = 'idle';
    }, 2000);
  }

  function handleEnter() {
    // Use the edited idleSeconds when it's a valid positive integer; fall
    // back to the last saved value (config.idle_seconds) when the input is
    // mid-edit / invalid, so the cookie can never carry NaN.
    const idleForCookie =
      Number.isInteger(idleSeconds) && idleSeconds >= 1 ? idleSeconds : config.idle_seconds;
    setKioskCookies(config.id, idleForCookie);
    location.assign('/kiosk');
  }

  function handleExit() {
    clearKioskCookies();
    activeId = null;
  }

  async function deleteKiosk() {
    if (deleting) return;
    if (!confirm(`Delete kiosk ${idLabel}? This cannot be undone.`)) return;

    // Clear cookies BEFORE the API call when this device IS the active
    // kiosk, so the cookies are gone even if the user closes the tab
    // mid-request.
    if (getKioskConfigIdFromCookie() === config.id) clearKioskCookies();

    deleting = true;
    errorMessage = null;
    const { error, response } = await client.DELETE('/api/kiosk/configs/{config_id}/', {
      params: { path: { config_id: config.id } },
    });

    if (response?.status !== 204) {
      deleting = false;
      const parsed = parseApiError(error);
      errorMessage = parsed.message || 'Failed to delete kiosk.';
      return;
    }

    toast.success(`Deleted kiosk ${idLabel}.`, { persistUntilNav: true });
    await goto(resolve('/kiosk/edit'));
  }
</script>

<svelte:head>
  <title>Edit kiosk {idLabel}</title>
</svelte:head>

<Page width="extra-wide">
  <div class="header-row">
    <Breadcrumb crumbs={[{ label: 'Kiosks', href: '/kiosk/edit' }]} />
    <output class="save-status">
      {#if saveStatus === 'saving'}Saving…{:else if saveStatus === 'saved'}Saved{/if}
    </output>
  </div>
  <TwoColumnLayout>
    {#snippet main()}
      <div class="mobile-actions">
        <Button variant="destructive" fullWidth onclick={deleteKiosk} disabled={deleting}>
          {deleting ? 'Deleting…' : 'Delete Kiosk'}
        </Button>
        {#if isActive}
          <Button variant="primary" fullWidth onclick={handleExit}>Exit Kiosk Mode</Button>
        {:else}
          <Button variant="primary" fullWidth onclick={handleEnter}>Enter Kiosk Mode</Button>
        {/if}
      </div>

      {#if errorMessage}
        <StatusMessage variant="error">{errorMessage}</StatusMessage>
      {/if}

      <section class="settings">
        <label>
          <span>Front door heading</span>
          <input type="text" bind:value={pageHeading} maxlength="60" onblur={save} />
        </label>
        <label>
          <span>Idle timeout (seconds)</span>
          <input type="number" min="1" bind:value={idleSeconds} onblur={save} />
        </label>
      </section>

      <section class="machines">
        <label class="search">
          <span>Add a machine</span>
          <input
            type="search"
            placeholder="Search by name…"
            bind:value={search}
            autocomplete="off"
          />
        </label>

        {#if searchResults.length > 0}
          <ul class="results">
            {#each searchResults as t (t.slug)}
              <li>
                <button type="button" onclick={() => addTitle(t)}>
                  <strong>{t.name}</strong>
                  <span class="result-meta">
                    {#if t.manufacturer}{t.manufacturer.name}{/if}
                    {#if t.year}· {t.year}{/if}
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}

        <hr class="divider" />

        {#if items.length === 0}
          <p class="empty">No machines added yet.</p>
        {:else}
          <ol class="items">
            {#each items as item, i (item.titleSlug)}
              {@const t = titleBySlug.get(item.titleSlug)}
              <li class="item">
                <div class="item-header">
                  <span class="item-name">
                    {t?.name ?? item.titleName}
                    {#if t?.year}<span class="dim"> · {t.year}</span>{/if}
                    {#if t?.manufacturer}<span class="dim"> · {t.manufacturer.name}</span>{/if}
                  </span>
                  <div class="item-actions">
                    <button
                      type="button"
                      onclick={() => moveUp(i)}
                      disabled={i === 0}
                      aria-label="Move up">↑</button
                    >
                    <button
                      type="button"
                      onclick={() => moveDown(i)}
                      disabled={i === items.length - 1}
                      aria-label="Move down">↓</button
                    >
                    <button type="button" onclick={() => removeAt(i)} aria-label="Remove">✕</button>
                  </div>
                </div>
                <input
                  type="text"
                  placeholder="Hook (optional, e.g. 'First talking pinball machine')"
                  bind:value={item.hook}
                  maxlength={HOOK_MAX_LENGTH}
                  onblur={save}
                />
              </li>
            {/each}
          </ol>
        {/if}
      </section>
    {/snippet}

    {#snippet sidebar()}
      <div class="sidebar-desktop-only">
        <SidebarSection heading="Edit kiosk">
          <p class="about">
            Pick the machines to feature and set how long the browser sits idle before resetting to
            the kiosk home screen.
          </p>
          <div class="sidebar-action">
            <Button variant="destructive" fullWidth onclick={deleteKiosk} disabled={deleting}>
              {deleting ? 'Deleting…' : 'Delete Kiosk'}
            </Button>
          </div>
          <div class="sidebar-action">
            {#if isActive}
              <Button variant="primary" fullWidth onclick={handleExit}>Exit Kiosk Mode</Button>
            {:else}
              <Button variant="primary" fullWidth onclick={handleEnter}>Enter Kiosk Mode</Button>
            {/if}
          </div>
        </SidebarSection>
      </div>
    {/snippet}
  </TwoColumnLayout>
</Page>

<style>
  .about {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-2);
    line-height: 1.5;
  }

  .about:last-child {
    margin-bottom: 0;
  }

  .sidebar-action {
    margin-top: var(--size-3);
  }

  .sidebar-desktop-only {
    display: none;
  }
  @media (--breakpoint-wide) {
    .sidebar-desktop-only {
      display: contents;
    }
  }

  .header-row {
    display: flex;
    align-items: baseline;
    gap: var(--size-3);
    margin-bottom: var(--size-3);
  }
  .save-status {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0;
  }

  .mobile-actions {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
    margin-bottom: var(--size-5);
  }
  @media (--breakpoint-wide) {
    .mobile-actions {
      display: none;
    }
  }

  .settings {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--size-4);
    margin-bottom: var(--size-5);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
    font-size: var(--font-size-1);
  }

  label > span {
    color: var(--color-text-muted);
  }

  input[type='text'],
  input[type='search'],
  input[type='number'] {
    padding: var(--size-2) var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    font-size: var(--font-size-1);
  }

  .divider {
    margin: var(--size-5) 0 var(--size-3);
    border: none;
    border-top: 3px solid var(--color-border-soft);
  }

  .results {
    list-style: none;
    padding: 0;
    margin: var(--size-2) 0 0;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    max-height: 18rem;
    overflow-y: auto;
  }

  .results li {
    border-bottom: 1px solid var(--color-border-soft);
  }

  .results li:last-child {
    border-bottom: none;
  }

  .results button {
    width: 100%;
    text-align: left;
    background: transparent;
    border: none;
    padding: var(--size-2) var(--size-3);
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .results button:hover {
    background: var(--color-surface-muted);
  }

  .result-meta {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .items {
    list-style: none;
    padding: 0;
    margin: var(--size-3) 0 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .item {
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
    padding: var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
  }

  .item-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--size-2);
  }

  .item-name {
    font-weight: 600;
  }

  .dim {
    color: var(--color-text-muted);
    font-weight: 400;
  }

  .item-actions {
    display: flex;
    gap: var(--size-1);
  }

  .item-actions button {
    background: transparent;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-1) var(--size-2);
    cursor: pointer;
    min-width: 2rem;
    transition:
      background-color 0.15s ease,
      border-color 0.15s ease;
  }

  .item-actions button:hover:not(:disabled) {
    /* Neutral 8% tint, matches .btn-secondary hover — works in light + dark
       without inventing tokens. */
    background: color-mix(in srgb, var(--color-text) 8%, transparent);
    border-color: var(--color-text-muted);
  }

  .item-actions button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .empty {
    color: var(--color-text-muted);
    font-style: italic;
    margin-top: var(--size-3);
  }
</style>
