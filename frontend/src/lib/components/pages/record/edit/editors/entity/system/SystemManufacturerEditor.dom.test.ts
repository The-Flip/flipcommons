import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SystemManufacturerEditorFixture from './SystemManufacturerEditor.fixture.svelte';

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

// Rows the autocomplete endpoint returns, filtered by the typed query below.
const AUTOCOMPLETE_ROWS = [
  { value: 'stern', label: 'Stern Pinball', sublabel: null },
  { value: 'bally', label: 'Bally', sublabel: null },
];

const INITIAL = {
  manufacturer: { public_id: 'williams', name: 'Williams' },
};

/** The combobox input — accessible-named by the "Manufacturer" label. */
function getCombobox() {
  return screen.getByRole('combobox', { name: /manufacturer/i });
}

function mockResponses() {
  GET.mockImplementation(async (path: string, opts?: { params?: { query?: { q?: string } } }) => {
    if (path === '/api/entity-autocomplete/') {
      const q = (opts?.params?.query?.q ?? '').toLowerCase();
      const results = AUTOCOMPLETE_ROWS.filter((r) => r.label.toLowerCase().includes(q));
      return { data: { results }, error: undefined, response: { status: 200 } };
    }
    // Any load-all call (e.g. the retired /api/manufacturers/all/) is a regression.
    throw new Error(`Unexpected GET ${path}`);
  });
  PATCH.mockResolvedValue({ data: { slug: 'wpc-95' }, error: undefined });
}

describe('SystemManufacturerEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockResponses();
  });

  it('reports clean state initially', async () => {
    const user = userEvent.setup();
    render(SystemManufacturerEditorFixture, { props: { initialData: INITIAL } });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');
  });

  it('does not PATCH when saving a clean form', async () => {
    const user = userEvent.setup();
    render(SystemManufacturerEditorFixture, { props: { initialData: INITIAL } });

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).not.toHaveBeenCalled();
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('renders the saved manufacturer on mount with no autocomplete request', () => {
    render(SystemManufacturerEditorFixture, { props: { initialData: INITIAL } });

    // The seeded label paints from initialSelection — no network on mount.
    expect(getCombobox()).toHaveValue('Williams');
    expect(GET).not.toHaveBeenCalled();
  });

  it('hides the clear (×) because manufacturer is required', () => {
    render(SystemManufacturerEditorFixture, { props: { initialData: INITIAL } });

    expect(screen.queryByRole('button', { name: /clear selection/i })).not.toBeInTheDocument();
  });

  it('searches the entity-autocomplete endpoint, selects a row, and PATCHes the change', async () => {
    const user = userEvent.setup();
    render(SystemManufacturerEditorFixture, { props: { initialData: INITIAL } });

    // Focus fires the empty-query search; the endpoint is hit with the right shape.
    await user.click(getCombobox());
    expect(GET).toHaveBeenCalledWith('/api/entity-autocomplete/', {
      params: { query: { type: 'manufacturer', q: '' } },
    });

    // Type to narrow; the debounced query reaches the endpoint as `stern`.
    await user.type(getCombobox(), 'stern');
    await waitFor(() =>
      expect(GET).toHaveBeenLastCalledWith('/api/entity-autocomplete/', {
        params: { query: { type: 'manufacturer', q: 'stern' } },
      }),
    );

    const option = await screen.findByRole('option', { name: /stern pinball/i });
    await fireEvent.pointerDown(option);

    // The selection makes the form dirty and shows the new label.
    await waitFor(() => expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true'));
    expect(getCombobox()).toHaveValue('Stern Pinball');

    // Saving sends only the changed manufacturer field.
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/systems/{public_id}/claims/',
      expect.objectContaining({
        params: { path: { public_id: 'wpc-95' } },
        body: expect.objectContaining({ fields: { manufacturer: 'stern' } }),
      }),
    );

    // The retired load-all feeder is never touched (any arg shape).
    const calledPaths = GET.mock.calls.map((call) => call[0]);
    expect(calledPaths).not.toContain('/api/manufacturers/all/');
  });
});
