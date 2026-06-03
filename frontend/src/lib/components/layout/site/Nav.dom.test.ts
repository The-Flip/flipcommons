// Responsive bar layout (desktop vs tablet vs mobile) is verified visually,
// not in JSDOM — these tests cover the menu contents per auth state. The
// mobile-menu test mocks matchMedia to flip the isMobile flag; everything
// else relies on the default JSDOM matchMedia stub (matches: false).
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { pageState, auth } = vi.hoisted(() => ({
  pageState: {
    url: new URL('http://localhost:5173/'),
    params: {} as Record<string, string>,
  },
  auth: {
    isAuthenticated: false,
    username: null as string | null,
    firstName: '',
    lastName: '',
    loaded: true,
    capabilities: {} as Record<string, boolean>,
    load: () => Promise.resolve(),
    logout: vi.fn(() => Promise.resolve()),
    can(activity: string) {
      return this.capabilities[activity] === true;
    },
  },
}));

vi.mock('$app/state', () => ({ page: pageState }));
vi.mock('$app/paths', () => ({ resolve: (p: string) => p }));
vi.mock('$lib/auth.svelte', () => ({ auth }));

import Nav from './Nav.svelte';
import { toast } from '$lib/toast/toast.svelte';

function setAuth(overrides: Partial<typeof auth>) {
  Object.assign(auth, {
    isAuthenticated: false,
    username: null,
    firstName: '',
    lastName: '',
    loaded: true,
    capabilities: {},
    logout: vi.fn(() => Promise.resolve()),
  });
  Object.assign(auth, overrides);
}

describe('Nav', () => {
  beforeEach(() => {
    pageState.url = new URL('http://localhost:5173/');
    toast._resetForTest();
  });

  it('anonymous: renders Sign in link, no avatar, no admin items', async () => {
    const user = userEvent.setup();
    setAuth({});
    render(Nav);

    expect(screen.getByRole('link', { name: 'Sign In' })).toBeInTheDocument();
    expect(screen.queryByTestId('avatar')).not.toBeInTheDocument();

    // Open the hamburger and confirm there's no admin section.
    await user.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.queryByText('admin')).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Django Admin' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Sign In' })).toBeInTheDocument();
  });

  it('authed non-superuser: avatar with initials, menu has My Contributions + Sign Out, no admin', async () => {
    const user = userEvent.setup();
    setAuth({
      isAuthenticated: true,
      username: 'alice',
      firstName: 'Alice',
      lastName: 'Anderson',
    });
    render(Nav);

    expect(screen.getByTestId('avatar')).toHaveTextContent('AA');

    await user.click(screen.getByRole('button', { name: 'Account menu' }));
    expect(screen.getByRole('menuitem', { name: 'My Contributions' })).toHaveAttribute(
      'href',
      '/users/alice',
    );
    expect(screen.getByRole('menuitem', { name: 'Sign Out' })).toBeInTheDocument();
    expect(screen.queryByText('admin')).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Django Admin' })).not.toBeInTheDocument();
  });

  it('authed with both kiosk.edit and django_admin.access: admin section shows both links', async () => {
    const user = userEvent.setup();
    setAuth({
      isAuthenticated: true,
      capabilities: { 'kiosk.edit': true, 'django_admin.access': true },
      username: 'root',
      firstName: 'Root',
      lastName: 'User',
    });
    render(Nav);

    await user.click(screen.getByRole('button', { name: 'Account menu' }));

    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Kiosks' })).toHaveAttribute('href', '/kiosk/edit');
    expect(screen.getByRole('menuitem', { name: 'Django Admin' })).toHaveAttribute(
      'href',
      '/djadmin/',
    );
  });

  it('authed staff (django_admin.access only): admin section shows Django Admin, no Kiosks', async () => {
    const user = userEvent.setup();
    setAuth({
      isAuthenticated: true,
      capabilities: { 'django_admin.access': true },
      username: 'staff',
      firstName: 'Staff',
      lastName: 'Person',
    });
    render(Nav);

    await user.click(screen.getByRole('button', { name: 'Account menu' }));

    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Kiosks' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Django Admin' })).toBeInTheDocument();
  });

  it('authed kiosk-only (no django_admin.access): admin section shows Kiosks only', async () => {
    const user = userEvent.setup();
    setAuth({
      isAuthenticated: true,
      capabilities: { 'kiosk.edit': true },
      username: 'kioskadmin',
      firstName: 'Kiosk',
      lastName: 'Admin',
    });
    render(Nav);

    await user.click(screen.getByRole('button', { name: 'Account menu' }));

    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Kiosks' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Django Admin' })).not.toBeInTheDocument();
  });

  it('Sign Out menu item calls auth.logout()', async () => {
    const user = userEvent.setup();
    setAuth({
      isAuthenticated: true,
      username: 'alice',
      firstName: 'Alice',
      lastName: 'Anderson',
    });
    render(Nav);

    await user.click(screen.getByRole('button', { name: 'Account menu' }));
    await user.click(screen.getByRole('menuitem', { name: 'Sign Out' }));

    expect(auth.logout).toHaveBeenCalledTimes(1);
    // Wait a microtask for the awaited logout to resolve before checking the toast.
    await Promise.resolve();
    expect(toast.messages.map((m) => m.text)).toContain('Signed out');
  });

  it('hamburger renders even when auth has not loaded yet', async () => {
    setAuth({ loaded: false });
    render(Nav);

    // Hamburger trigger must always be reachable so mobile users can open
    // the primary nav before /api/auth/me/ resolves.
    expect(screen.getByRole('button', { name: 'Menu' })).toBeInTheDocument();
    // Auth-dependent menu items must not appear yet.
    expect(screen.queryByRole('menuitem', { name: 'Sign In' })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Sign Out' })).not.toBeInTheDocument();
  });

  describe('mobile (width <= 40rem)', () => {
    let originalMatchMedia: typeof window.matchMedia;

    beforeEach(() => {
      originalMatchMedia = window.matchMedia;
      window.matchMedia = ((query: string) => ({
        matches: query === '(max-width: 40rem)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
        onchange: null,
      })) as unknown as typeof window.matchMedia;
    });

    afterEach(() => {
      window.matchMedia = originalMatchMedia;
    });

    it('hamburger menu includes Titles / Manufacturers / People plus Changelog', async () => {
      const user = userEvent.setup();
      setAuth({});
      render(Nav);

      await user.click(screen.getByRole('button', { name: 'Menu' }));
      expect(screen.getByRole('menuitem', { name: 'Titles' })).toHaveAttribute('href', '/titles');
      expect(screen.getByRole('menuitem', { name: 'Manufacturers' })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: 'People' })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: 'Changelog' })).toBeInTheDocument();
    });
  });

  it('tablet (default JSDOM matchMedia): hamburger menu does NOT include primary nav items', async () => {
    const user = userEvent.setup();
    setAuth({});
    render(Nav);

    await user.click(screen.getByRole('button', { name: 'Menu' }));
    // Primary nav stays in the bar at tablet width; only Changelog appears
    // in the menu (under "activity").
    expect(screen.queryByRole('menuitem', { name: 'Titles' })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Manufacturers' })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'People' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Changelog' })).toBeInTheDocument();
  });
});
