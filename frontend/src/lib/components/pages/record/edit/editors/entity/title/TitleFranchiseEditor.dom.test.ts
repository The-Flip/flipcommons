import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TitleFranchiseEditorFixture from './TitleFranchiseEditor.fixture.svelte';

const { GET, PATCH } = vi.hoisted(() => ({
  GET: vi.fn(),
  PATCH: vi.fn(),
}));

const { invalidateAll } = vi.hoisted(() => ({
  invalidateAll: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  default: { GET, PATCH },
}));

vi.mock('$app/navigation', () => ({
  invalidateAll,
}));

// Rows the autocomplete endpoint returns per type, filtered by the typed query.
const FRANCHISE_ROWS = [
  { value: 'addams-family', label: 'Addams Family', sublabel: null },
  { value: 'star-wars', label: 'Star Wars', sublabel: null },
];
const SERIES_ROWS = [{ value: 'addams-series', label: 'Addams Series', sublabel: null }];

const INITIAL_TITLE = {
  franchise: { public_id: 'addams-family', name: 'Addams Family' },
  series: null,
};

function mockResponses() {
  GET.mockImplementation(
    async (path: string, opts?: { params?: { query?: { type?: string; q?: string } } }) => {
      if (path === '/api/entity-autocomplete/') {
        const type = opts?.params?.query?.type;
        const q = (opts?.params?.query?.q ?? '').toLowerCase();
        const rows = type === 'series' ? SERIES_ROWS : FRANCHISE_ROWS;
        const results = rows.filter((r) => r.label.toLowerCase().includes(q));
        return { data: { results }, error: undefined, response: { status: 200 } };
      }
      // The retired /api/franchises/all/ + /api/series/all/ feeders must not be hit.
      throw new Error(`Unexpected GET ${path}`);
    },
  );
  PATCH.mockResolvedValue({ data: {}, error: undefined });
}

describe('TitleFranchiseEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockResponses();
  });

  it('reports clean state initially with the saved franchise rendered (no network)', async () => {
    render(TitleFranchiseEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    expect(screen.getByRole('combobox', { name: 'Franchise' })).toHaveValue('Addams Family');
    expect(GET).not.toHaveBeenCalled();
    expect(screen.getByTestId('dirty')).toHaveTextContent('false');
  });

  it('does not PATCH when saving a clean form', async () => {
    const user = userEvent.setup();
    render(TitleFranchiseEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).not.toHaveBeenCalled();
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('clearing the franchise marks dirty and PATCHes franchise: null (the optional null path)', async () => {
    const user = userEvent.setup();
    render(TitleFranchiseEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    // The franchise is optional, so its clear (×) is present; clearing empties it.
    await user.click(screen.getByRole('button', { name: 'Clear selection' }));

    expect(screen.getByTestId('dirty')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/titles/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({ fields: { franchise: null } }),
      }),
    );
  });

  it('selecting a new franchise via the typeahead PATCHes the chosen slug', async () => {
    const user = userEvent.setup();
    render(TitleFranchiseEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    await user.click(screen.getByRole('combobox', { name: 'Franchise' }));
    expect(GET).toHaveBeenCalledWith('/api/entity-autocomplete/', {
      params: { query: { type: 'franchise', q: '' } },
    });

    await user.click(await screen.findByRole('option', { name: 'Star Wars' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/titles/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({ fields: { franchise: 'star-wars' } }),
      }),
    );
  });
});
