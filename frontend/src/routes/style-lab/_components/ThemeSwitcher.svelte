<script lang="ts">
  import { onMount } from 'svelte';
  import {
    THEMES,
    THEME_STORAGE_KEY,
    isThemeId,
    getTheme,
    normalizeThemeId,
    type ThemeId,
  } from '$lib/themes';

  // /style-lab-only component: deliberately NOT hardened against
  // localStorage / dynamic-import failures. If something here breaks, a
  // dev sees it loudly and fixes it. End users never reach this code.
  // The page-load bootstrap in lib/themes/index.ts IS hardened — that's
  // the path that runs for every visitor on every page.

  let selectedTheme = $state<ThemeId>('system');
  // Monotonic token so a slow CSS chunk from a previous selection can't
  // overwrite the DOM/storage after the user has moved on to another theme.
  let applyToken = 0;

  async function applyTheme(theme: ThemeId) {
    selectedTheme = theme;
    const token = ++applyToken;

    if (theme === 'system') {
      delete document.documentElement.dataset.theme;
      localStorage.removeItem(THEME_STORAGE_KEY);
      return;
    }

    await getTheme(theme).load();
    if (token !== applyToken) return;
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }

  function handleChange(event: Event) {
    const target = event.currentTarget;
    if (!(target instanceof HTMLSelectElement)) return;
    if (isThemeId(target.value)) void applyTheme(target.value);
  }

  onMount(() => {
    const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    const theme = storedTheme ? normalizeThemeId(storedTheme) : null;
    if (theme) {
      void applyTheme(theme);
    } else if (storedTheme) {
      localStorage.removeItem(THEME_STORAGE_KEY);
    }
  });
</script>

<div class="theme-switcher">
  <label for="theme-select">Theme</label>
  <select id="theme-select" value={selectedTheme} onchange={handleChange}>
    {#each THEMES as theme (theme.id)}
      <option value={theme.id}>{theme.label}</option>
    {/each}
  </select>
</div>

<style>
  .theme-switcher {
    display: flex;
    align-items: center;
    gap: var(--size-2);
  }

  label {
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
    font-weight: 600;
  }

  select {
    min-width: 10rem;
  }
</style>
