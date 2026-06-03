import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const { goto } = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$lib/auth.svelte', () => ({
  auth: { isAuthenticated: true, load: () => Promise.resolve() },
}));
// The fetchPage closure imports the client; it isn't called on initial render,
// but the import must resolve.
vi.mock('$lib/api/client', () => ({ default: { GET: vi.fn() } }));
// The adapter emits MetaTags + listing JSON-LD, which read `page.url`.
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/systems') } }));

import Page from './+page.svelte';

const WPC = {
  name: 'WPC-95',
  slug: 'wpc-95',
  manufacturer: { public_id: 'williams', name: 'Williams' },
  model_count: 30,
};
const SPIKE = {
  name: 'SPIKE',
  slug: 'spike',
  manufacturer: { public_id: 'stern', name: 'Stern' },
  model_count: 42,
};

const OPTIONS = [
  { value: 'stern', name: 'Stern' },
  { value: 'williams', name: 'Williams' },
];

function data(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      items: [WPC, SPIKE],
      count: 2,
      q: '',
      manufacturer: '',
      manufacturerOptions: OPTIONS,
      ...overrides,
    },
  };
}

describe('/systems route — extraFilter axis', () => {
  it('renders SSR rows with manufacturer + model count', () => {
    render(Page, { props: data() });
    const list = screen.getByRole('list');
    expect(within(list).getByText('WPC-95')).toBeInTheDocument();
    expect(within(list).getByText('Williams')).toBeInTheDocument();
    expect(within(list).getByText('30 models')).toBeInTheDocument();
  });

  it('renders the server-derived manufacturer options, "All" first', () => {
    render(Page, { props: data() });
    const select = screen.getByLabelText('Manufacturer') as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      'All manufacturers',
      'Stern',
      'Williams',
    ]);
  });

  it('selecting a manufacturer navigates to ?manufacturer=', async () => {
    const user = userEvent.setup();
    render(Page, { props: data() });

    await user.selectOptions(screen.getByLabelText('Manufacturer'), 'williams');

    await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
    expect(goto.mock.calls[0][0]).toContain('manufacturer=williams');
  });

  it('offers the create prompt for an empty search when no filter is active', () => {
    // Positive control for the suppression test below: same empty+query, but
    // *unfiltered*, so `count === 0` genuinely means the name is free.
    render(Page, { props: data({ items: [], count: 0, q: 'nonesuch', manufacturer: '' }) });
    expect(screen.getByText(/does not exist/i)).toBeInTheDocument();
  });

  it('suppresses the create prompt when a manufacturer filter is active and the page is empty', () => {
    render(Page, {
      props: data({ items: [], count: 0, q: 'nonesuch', manufacturer: 'williams' }),
    });
    // count===0 under an active filter means "none for this manufacturer", not
    // "the name is free" — so no create offer, just the empty message.
    expect(screen.queryByText(/does not exist/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no matching systems/i)).toBeInTheDocument();
  });
});
