import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockGet, authMock } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  authMock: { isAuthenticated: true, load: () => Promise.resolve() },
}));

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/paths', () => ({ resolve: (p: string) => p }));
vi.mock('$lib/api/client', () => ({
  default: { GET: mockGet },
}));
vi.mock('$lib/auth.svelte', () => ({ auth: authMock }));

import Page from './+page.svelte';
import type { SystemListItemSchema } from '$lib/api/schema';

const SYSTEMS = [
  {
    name: 'SPIKE',
    slug: 'spike',
    manufacturer: { public_id: 'stern', name: 'Stern' },
    model_count: 42,
  },
  {
    name: 'WPC-95',
    slug: 'wpc-95',
    manufacturer: { public_id: 'williams', name: 'Williams' },
    model_count: 30,
  },
  {
    name: 'Whitestar',
    slug: 'whitestar',
    manufacturer: { public_id: 'stern', name: 'Stern' },
    model_count: 12,
  },
] satisfies SystemListItemSchema[];

async function renderAndWait() {
  mockGet.mockResolvedValue({ data: SYSTEMS });
  render(Page);
  // createAsyncLoader resolves on the next tick; wait for the list to
  // appear, then scope subsequent queries to it so the overview paragraph
  // in the page header (which also mentions systems like WPC-95) doesn't
  // collide with row-level text matches.
  const list = await screen.findByRole('list');
  return within(list);
}

describe('systems list route', () => {
  beforeEach(() => {
    mockGet.mockReset();
    authMock.isAuthenticated = true;
  });

  it('renders all systems with manufacturer and model count', async () => {
    const list = await renderAndWait();
    expect(list.getByText('SPIKE')).toBeInTheDocument();
    expect(list.getByText('WPC-95')).toBeInTheDocument();
    expect(list.getByText('Whitestar')).toBeInTheDocument();
    expect(list.getAllByText('Stern').length).toBe(2);
    expect(list.getByText('42 models')).toBeInTheDocument();
    expect(list.getByText('30 models')).toBeInTheDocument();
  });

  it('derives manufacturer options from visible systems', async () => {
    await renderAndWait();
    const select = screen.getByLabelText('Manufacturer') as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((o) => o.textContent);
    // First entry is "All manufacturers"; Stern + Williams follow in
    // alphabetical order. Stern appears once despite two systems owning it.
    expect(optionLabels).toEqual(['All manufacturers', 'Stern', 'Williams']);
  });

  it('manufacturer filter narrows the rendered list', async () => {
    const user = userEvent.setup();
    const list = await renderAndWait();

    const select = screen.getByLabelText('Manufacturer') as HTMLSelectElement;
    await user.selectOptions(select, 'williams');

    expect(list.getByText('WPC-95')).toBeInTheDocument();
    expect(list.queryByText('SPIKE')).not.toBeInTheDocument();
    expect(list.queryByText('Whitestar')).not.toBeInTheDocument();
  });

  it('shows "+ New System" in the action menu when authenticated', async () => {
    const user = userEvent.setup();
    await renderAndWait();
    // The action-menu trigger is labeled "Edit" by EditSectionMenu's default.
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getByRole('menuitem', { name: /\+ New System/ })).toBeInTheDocument();
  });

  it('hides the action-menu trigger entirely when unauthenticated', async () => {
    authMock.isAuthenticated = false;
    mockGet.mockResolvedValue({ data: SYSTEMS });
    render(Page);
    const list = await screen.findByRole('list');
    expect(within(list).getByText('SPIKE')).toBeInTheDocument();
    // The trigger itself is gated on auth, so there is no Edit button to
    // click — and therefore no way to reveal the create item.
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
  });
});
