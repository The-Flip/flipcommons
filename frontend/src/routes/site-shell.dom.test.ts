import { render, screen } from '@testing-library/svelte';
import type { RouteId } from '$app/types';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';

const { pageState } = vi.hoisted(() => ({
  pageState: {
    url: new URL('http://localhost/'),
    route: { id: '/' as string | null },
    params: {} as Record<string, string>,
  },
}));

vi.mock('$app/state', () => ({
  page: pageState,
  updated: { current: false },
}));
vi.mock('$app/navigation', () => ({
  beforeNavigate: vi.fn(),
  afterNavigate: vi.fn(),
  goto: vi.fn(),
}));
vi.mock('$app/paths', () => ({ resolve: (p: string) => p, asset: (p: string) => p }));
vi.mock('$lib/analytics', () => ({}));
vi.mock('$lib/auth.svelte', () => ({
  auth: { isAuthenticated: false, user: null, load: () => Promise.resolve() },
}));
vi.mock('$lib/themes', () => ({ bootstrapTheme: () => Promise.resolve() }));
vi.mock('$lib/kiosk/config', () => ({ isKioskCookieSet: () => false }));

const Layout = (await import('./+layout.svelte')).default;

/** Stands in for the page the layout wraps; its content is irrelevant here. */
const pageContent = createRawSnippet(() => ({ render: () => '<p>page</p>' }));

/** Renders the root layout at a URL/route pair, as SvelteKit would. */
function renderAt(pathname: string, routeId: RouteId | null) {
  pageState.url = new URL(`http://localhost${pathname}`);
  pageState.route.id = routeId;
  return render(Layout, { props: { children: pageContent } });
}

function hasSiteChrome(): boolean {
  return (
    screen.queryByRole('navigation', { name: 'Primary' }) !== null ||
    document.querySelector('footer.site-footer') !== null
  );
}

describe('root layout shell selection', () => {
  it('gives a detail page the full site shell', () => {
    renderAt('/locations/canada', '/locations/[...path]');
    expect(hasSiteChrome()).toBe(true);
  });

  it('gives a top-level location sub-route focus chrome', () => {
    renderAt('/locations/canada/edit-history', '/locations/[...path]/edit-history');
    expect(hasSiteChrome()).toBe(false);
  });

  it('gives a nested location sub-route focus chrome', () => {
    // A Location's public_id spans several URL segments (`canada/on`), which
    // is the case any position-based classifier gets wrong.
    renderAt('/locations/canada/on/edit-history', '/locations/[...path]/edit-history');
    expect(hasSiteChrome()).toBe(false);
  });

  it('gives signup the minimal shell — footer, no primary nav', () => {
    renderAt('/signup', '/signup');
    expect(screen.queryByRole('navigation', { name: 'Primary' })).toBeNull();
    expect(document.querySelector('footer.site-footer')).not.toBeNull();
  });
});
