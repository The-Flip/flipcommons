import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { authMock } = vi.hoisted(() => ({
  authMock: { isAuthenticated: true, load: () => Promise.resolve() },
}));

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/paths', () => ({ resolve: (p: string) => p }));
vi.mock('$app/state', () => ({
  page: {
    params: { slug: 'wpc-95' },
    url: new URL('http://localhost/systems/wpc-95'),
  },
}));
vi.mock('$lib/auth.svelte', () => ({ auth: authMock }));

// The layout mounts SectionEditorHost, which initializes editor machinery
// we don't need for an action-menu test. Stub it to a no-op so we can
// focus on the action-bar behavior.
vi.mock('$lib/components/SectionEditorHost.svelte', async () => {
  const Stub = (await import('./__stubs__/empty-component.svelte')).default;
  return { default: Stub };
});

import Layout from './+layout.svelte';
import type { SystemDetailSchema } from '$lib/api/schema';

const SYSTEM = {
  name: 'WPC-95',
  slug: 'wpc-95',
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  manufacturer: { name: 'Williams', public_id: 'williams' },
  technology_subgeneration: null,
  titles: [],
  sibling_systems: [],
} satisfies SystemDetailSchema;

function renderLayout() {
  render(Layout, {
    data: { system: SYSTEM },
    children: () => ({}) as never,
  } as unknown as Parameters<typeof render>[1]);
}

describe('systems detail layout — action menu', () => {
  beforeEach(() => {
    authMock.isAuthenticated = true;
  });

  it('authenticated users see Delete System as the last menu item', async () => {
    const user = userEvent.setup();
    renderLayout();

    // Action-menu trigger is "Edit" (EditSectionMenu default label).
    await user.click(screen.getByRole('button', { name: 'Edit' }));

    const deleteItem = screen.getByRole('menuitem', { name: 'Delete System' });
    expect(deleteItem).toBeInTheDocument();
    expect(deleteItem).toHaveAttribute('href', '/systems/wpc-95/delete');

    // Delete must be the last menu item — "destructive action last".
    const items = screen.getAllByRole('menuitem');
    expect(items[items.length - 1]).toBe(deleteItem);
  });

  it('unauthenticated users get no Edit menu at all', () => {
    authMock.isAuthenticated = false;
    renderLayout();

    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByText('Delete System')).toBeNull();
  });
});
