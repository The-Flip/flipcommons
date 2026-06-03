import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';

import Harness from './RecordDetailShell.test-harness.svelte';

describe('RecordDetailShell', () => {
  it('renders hero, action bar, main, and sidebar when all are provided', () => {
    const { body } = render(Harness, {
      props: { showActionBar: true, showSidebar: true },
    });

    expect(body).toContain('Medieval Madness');
    expect(body).toContain('Page actions');
    expect(body).toContain('Main content');
    expect(body).toContain('Sidebar content');
  });

  it('emits a two-column container when a sidebar is provided', () => {
    const { body } = render(Harness, {
      props: { showSidebar: true },
    });

    expect(body).toContain('<aside');
  });

  it('omits the two-column container and renders main directly when no sidebar', () => {
    const { body } = render(Harness, {
      props: { showActionBar: false, showSidebar: false },
    });

    expect(body).toContain('Main content');
    expect(body).not.toContain('<aside');
    expect(body).not.toContain('Sidebar content');
    expect(body).not.toContain('Page actions');
  });

  it('wraps the sidebar in the desktop-only container when sidebarDesktopOnly is true', () => {
    const { body } = render(Harness, {
      props: { showSidebar: true, sidebarDesktopOnly: true },
    });

    expect(body).toMatch(/class="[^"]*\bdesktop-only\b/);
  });

  it('does not apply the desktop-only wrapper when sidebarDesktopOnly is false', () => {
    const { body } = render(Harness, {
      props: { showSidebar: true, sidebarDesktopOnly: false },
    });

    expect(body).not.toContain('desktop-only');
  });
});
