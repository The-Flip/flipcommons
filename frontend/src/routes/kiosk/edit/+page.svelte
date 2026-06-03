<!--
  Superuser-only kiosk list. Each row is a saved KioskConfig; the row matching
  this device's `kioskConfigId` cookie shows an "Active on this device" pill
  and an "Exit Kiosk Mode" button in place of "Enter Kiosk Mode". Reading
  activeId server-side avoids an SSR/hydration flash.
-->
<script lang="ts">
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import client from '$lib/api/client';
  import { parseApiError } from '$lib/api/parse-api-error';
  import { toast } from '$lib/toast/toast.svelte';
  import { clearKioskCookies, setKioskCookies } from '$lib/kiosk/config';
  import Page from '$lib/components/layout/page/Page.svelte';
  import PageHeader from '$lib/components/layout/page/PageHeader.svelte';
  import TwoColumnLayout from '$lib/components/layout/page/TwoColumnLayout.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import StatusMessage from '$lib/components/ui/StatusMessage.svelte';
  import List from '$lib/components/ui/list/List.svelte';
  import ListItem from '$lib/components/ui/list/ListItem.svelte';
  import Button from '$lib/components/ui/Button.svelte';

  let { data } = $props();
  let configs = $derived(data.configs);
  // activeId comes from /kiosk/edit/+page.server.ts (reads kioskConfigId
  // cookie). Local mutable copy so exitKioskMode() can clear it without
  // a full reload.
  // svelte-ignore state_referenced_locally
  let activeId = $state<number | null>(data.activeId);
  let createError = $state<string | null>(null);
  let creating = $state(false);

  async function createKiosk() {
    if (creating) return;
    creating = true;
    createError = null;
    const { data: created, error } = await client.POST('/api/kiosk/configs/');
    creating = false;
    if (!created) {
      const parsed = parseApiError(error);
      createError = parsed.message || 'Failed to create kiosk.';
      return;
    }
    toast.success(`Created kiosk #${created.id}.`, { persistUntilNav: true });
    await goto(resolve(`/kiosk/edit/${created.id}`));
  }

  function enterKioskMode(config: { id: number; idle_seconds: number }) {
    setKioskCookies(config.id, config.idle_seconds);
    // Full reload (not goto) so the root layout's onMount-based KioskMode
    // mount gate runs and KioskMode mounts immediately.
    location.assign('/kiosk');
  }

  function exitKioskMode() {
    clearKioskCookies();
    activeId = null;
  }
</script>

<svelte:head>
  <title>Kiosks</title>
</svelte:head>

<Page width="extra-wide">
  <PageHeader title="Kiosks" />
  <TwoColumnLayout>
    {#snippet main()}
      <div class="create-row create-row--mobile">
        <Button variant="secondary" fullWidth onclick={createKiosk} disabled={creating}>
          {creating ? 'Creating…' : '+ New Kiosk'}
        </Button>
      </div>
      {#if createError}
        <StatusMessage variant="error">{createError}</StatusMessage>
      {/if}
      {#if configs.length === 0}
        <StatusMessage variant="empty">
          No kiosks yet. Click "+ New Kiosk" to add one.
        </StatusMessage>
      {:else}
        <List>
          {#each configs as config (config.id)}
            {@const isActive = config.id === activeId}
            <ListItem href={`/kiosk/edit/${config.id}`}>
              <span class="kiosk-name"
                >Kiosk #{config.id}{config.page_heading ? ` - ${config.page_heading}` : ''}</span
              >
              {#if isActive}
                <span class="active-pill">Active on this device</span>
              {/if}
              {#snippet actions()}
                {#if isActive}
                  <Button variant="primary" onclick={exitKioskMode}>Exit Kiosk Mode</Button>
                {:else}
                  <Button variant="primary" onclick={() => enterKioskMode(config)}>
                    Enter Kiosk Mode
                  </Button>
                {/if}
              {/snippet}
            </ListItem>
          {/each}
        </List>
      {/if}
    {/snippet}
    {#snippet sidebar()}
      <div class="sidebar-desktop-only">
        <SidebarSection heading="Kiosks">
          <p class="about">Display a curated list of machines on the front door of this device.</p>
        </SidebarSection>
        <div class="create-row create-row--desktop">
          <Button variant="secondary" fullWidth onclick={createKiosk} disabled={creating}>
            {creating ? 'Creating…' : '+ New Kiosk'}
          </Button>
        </div>
      </div>
    {/snippet}
  </TwoColumnLayout>
</Page>

<style>
  .sidebar-desktop-only {
    display: none;
  }
  @media (--breakpoint-wide) {
    .sidebar-desktop-only {
      display: contents;
    }
  }
  .create-row {
    margin-bottom: var(--size-3);
  }
  .create-row--desktop {
    display: none;
    margin-top: var(--size-3);
    margin-bottom: 0;
  }
  @media (--breakpoint-wide) {
    .create-row--mobile {
      display: none;
    }
    .create-row--desktop {
      display: block;
    }
  }
  .about {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-2);
    line-height: 1.5;
  }
  .kiosk-name {
    flex: 1;
    font-size: var(--font-size-2);
    font-weight: 600;
    color: var(--color-text);
  }
  .active-pill {
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-accent);
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-2);
    padding: 0 var(--size-2);
    line-height: 1.6;
  }
</style>
