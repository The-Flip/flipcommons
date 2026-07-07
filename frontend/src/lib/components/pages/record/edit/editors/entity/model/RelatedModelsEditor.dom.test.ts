import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import RelatedModelsEditorFixture from './RelatedModelsEditor.fixture.svelte';

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
// `medieval-madness` is the fixture's own model — it must be excluded.
const AUTOCOMPLETE_ROWS = [
  { value: 'medieval-madness', label: 'Medieval Madness', sublabel: null },
  { value: 'attack-from-mars', label: 'Attack from Mars', sublabel: null },
  { value: 'monster-bash', label: 'Monster Bash', sublabel: null },
];

function mockResponses() {
  GET.mockImplementation(async (path: string, opts?: { params?: { query?: { q?: string } } }) => {
    if (path === '/api/entity-autocomplete/') {
      const q = (opts?.params?.query?.q ?? '').toLowerCase();
      const results = AUTOCOMPLETE_ROWS.filter((r) => r.label.toLowerCase().includes(q));
      return { data: { results }, error: undefined, response: { status: 200 } };
    }
    // Any load-all call (e.g. the retired /api/models/edit-options/ lists) is a regression.
    throw new Error(`Unexpected GET ${path}`);
  });
  PATCH.mockResolvedValue({ data: { slug: 'medieval-madness' }, error: undefined });
}

describe('RelatedModelsEditor dirty-state contract', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockResponses();
  });

  const CLEAN = {
    variant_of: null,
    converted_from: null,
    remake_of: null,
    bootleg_of: null,
  };

  it('reports clean state initially and dirty + PATCHes the slug after selecting', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    await user.click(screen.getByRole('combobox', { name: 'Variant of' }));
    await user.click(await screen.findByRole('option', { name: 'Attack from Mars' }));

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/models/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({ fields: { variant_of: 'attack-from-mars' } }),
      }),
    );
  });

  it('PATCHes the bootleg_of field after selecting a bootleg source', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('combobox', { name: 'Bootleg of' }));
    await user.click(await screen.findByRole('option', { name: 'Attack from Mars' }));

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(PATCH).toHaveBeenCalledTimes(1));
    expect(PATCH).toHaveBeenCalledWith(
      '/api/models/{public_id}/claims/',
      expect.objectContaining({
        body: expect.objectContaining({ fields: { bootleg_of: 'attack-from-mars' } }),
      }),
    );
  });

  it('excludes the current model from its own related-model options', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, { props: { initialData: CLEAN } });

    await user.click(screen.getByRole('combobox', { name: 'Variant of' }));

    // The other models appear…
    expect(await screen.findByRole('option', { name: 'Attack from Mars' })).toBeInTheDocument();
    // …but the model can't be a variant of itself.
    expect(screen.queryByRole('option', { name: 'Medieval Madness' })).not.toBeInTheDocument();
  });
});
