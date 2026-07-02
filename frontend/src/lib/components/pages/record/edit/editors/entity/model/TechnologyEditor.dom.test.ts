import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TechnologyEditorFixture from './TechnologyEditor.fixture.svelte';

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

const EDIT_OPTIONS = {
  data: {
    technology_generations: [
      { slug: 'solid-state', label: 'Solid State' },
      { slug: 'dot-matrix-era', label: 'Dot Matrix Era' },
    ],
    technology_subgenerations: [
      { slug: 'wpc-95', label: 'WPC-95 subgen' },
      { slug: 'system-11', label: 'System 11' },
    ],
    display_types: [
      { slug: 'dmd', label: 'DMD' },
      { slug: 'lcd', label: 'LCD' },
    ],
    display_subtypes: [
      { slug: 'orange-dmd', label: 'Orange DMD' },
      { slug: 'color-dmd', label: 'Color DMD' },
    ],
    systems: [
      { slug: 'wpc-95', label: 'WPC-95' },
      { slug: 'spike-2', label: 'Spike 2' },
    ],
  },
};

const INITIAL_MODEL = {
  technology_generation: { public_id: 'solid-state' },
  technology_subgeneration: { public_id: 'wpc-95' },
  system: { public_id: 'wpc-95' },
  display_type: { public_id: 'dmd' },
  display_subtype: { public_id: 'orange-dmd' },
};

function mockGetResponses() {
  GET.mockImplementation(async (path: string) => {
    if (path === '/api/models/edit-options/') {
      return EDIT_OPTIONS;
    }

    throw new Error(`Unexpected GET ${path}`);
  });
}

function renderEditor(initialData = INITIAL_MODEL) {
  mockGetResponses();
  return render(TechnologyEditorFixture, {
    props: { initialData, slug: 'medieval-madness' },
  });
}

describe('TechnologyEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
  });

  it('renders FK dropdowns from edit-options data', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole('combobox', { name: 'Technology generation' }));
    expect(await screen.findByRole('option', { name: 'Solid State' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Dot Matrix Era' })).toBeInTheDocument();

    await user.click(screen.getByRole('combobox', { name: 'System' }));
    expect(await screen.findByRole('option', { name: 'WPC-95' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Spike 2' })).toBeInTheDocument();
  });

  it('reports clean state initially and dirty state after editing', async () => {
    const user = userEvent.setup();
    renderEditor();

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    // Clear the System combobox to mark dirty
    const systemCombobox = screen.getByRole('combobox', { name: 'System' });
    await user.click(systemCombobox);
    await user.click(screen.getByRole('option', { name: 'Spike 2' }));

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('save() with no changes calls onsaved() without PATCHing', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
    expect(PATCH).not.toHaveBeenCalled();
  });

  it('save() with a changed field calls PATCH with only the changed fields', async () => {
    const user = userEvent.setup();
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);
    renderEditor();

    await user.click(screen.getByRole('combobox', { name: 'System' }));
    await user.click(screen.getByRole('option', { name: 'Spike 2' }));

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: { system: 'spike-2' }, note: '', citations: [] },
    });
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('save() passes meta (note/citation) through to the PATCH body', async () => {
    const user = userEvent.setup();
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);
    renderEditor();

    await user.click(screen.getByRole('combobox', { name: 'Display type' }));
    await user.click(screen.getByRole('option', { name: 'LCD' }));

    await user.click(screen.getByRole('button', { name: 'Save with meta' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: {
        fields: { display_type: 'lcd' },
        note: 'Corrected per flyer',
        citations: [{ citation_source_id: 7, locator: 'p. 2' }],
      },
    });
  });
});
