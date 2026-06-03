<script lang="ts">
  import '../app.css';
  // Side-effect import: triggers the analytics module's adapter selection and
  // (when a real PUBLIC_POSTHOG_KEY is set in the browser) PostHog init.
  import '$lib/analytics';
  import { page, updated } from '$app/state';
  import { beforeNavigate } from '$app/navigation';
  import SiteShell from '$lib/components/layout/site/SiteShell.svelte';
  import FocusSiteShell from '$lib/components/layout/site/FocusSiteShell.svelte';
  import MinimalSiteShell from '$lib/components/layout/site/MinimalSiteShell.svelte';
  import ToastHost from '$lib/toast/ToastHost.svelte';
  import { isFocusModePath, isMinimalShellPath } from '$lib/focus-mode';
  import { isKioskCookieSet } from '$lib/kiosk/config';
  import { bootstrapTheme } from '$lib/themes';
  import { onMount } from 'svelte';

  // When SvelteKit's version.json poll detects a new deploy, swap the next
  // soft navigation for a full reload so the user picks up new JS (and any
  // in-memory caches drop) without disrupting them mid-task.
  beforeNavigate(({ willUnload, to }) => {
    if (updated.current && !willUnload && to?.url) {
      location.href = to.url.href;
    }
  });

  let { children } = $props();

  let isFocusMode = $derived(isFocusModePath(page.url.pathname));
  let isMinimalShell = $derived(isMinimalShellPath(page.url.pathname));

  // Cookie is checked client-side so the kiosk path doesn't pollute every
  // page's load type. KioskMode itself is client-only (window event listeners).
  let isKiosk = $state(false);
  onMount(() => {
    isKiosk = isKioskCookieSet();
    void bootstrapTheme();
  });
</script>

<div class="app-root">
  {#if isMinimalShell}
    <MinimalSiteShell>
      {@render children()}
    </MinimalSiteShell>
  {:else if isFocusMode}
    <FocusSiteShell>
      {@render children()}
    </FocusSiteShell>
  {:else}
    <SiteShell>
      {@render children()}
    </SiteShell>
  {/if}

  <ToastHost />

  {#if isKiosk}
    {#await import('$lib/kiosk/KioskMode.svelte') then m}
      <m.default />
    {/await}
  {/if}
</div>

<style>
  .app-root {
    display: flex;
    flex-direction: column;
    min-height: 100dvh;
  }
</style>
