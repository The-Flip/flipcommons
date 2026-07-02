import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import FeaturesEditorFixture from './FeaturesEditor.fixture.svelte';

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

// Closed enumerations still come from /api/models/edit-options/ (SearchableSelect).
const EDIT_OPTIONS = {
  data: {
    tags: [
      { slug: 'classic', label: 'Classic' },
      { slug: 'widebody', label: 'Widebody' },
    ],
    reward_types: [
      { slug: 'replay', label: 'Replay' },
      { slug: 'extra-ball', label: 'Extra Ball' },
    ],
    cabinets: [
      { slug: 'standard', label: 'Standard' },
      { slug: 'widebody', label: 'Widebody' },
    ],
  },
};

// themes + gameplay_features are now typeaheads over /api/entity-autocomplete/.
const THEME_ROWS = [
  { value: 'medieval', label: 'Medieval', sublabel: null },
  { value: 'fantasy', label: 'Fantasy', sublabel: null },
];
const GF_ROWS = [
  { value: 'multiball', label: 'Multiball', sublabel: null },
  { value: 'ramps', label: 'Ramps', sublabel: null },
];

const FIELD_CONSTRAINTS = {
  data: {
    player_count: { min: 1, max: 6, step: 1 },
    flipper_count: { min: 0, max: 8, step: 1 },
  },
};

const INITIAL_MODEL = {
  themes: [{ public_id: 'medieval', name: 'Medieval' }],
  tags: [{ public_id: 'classic' }],
  reward_types: [{ public_id: 'replay' }],
  gameplay_features: [{ public_id: 'multiball', name: 'Multiball', count: 3 }],
  cabinet: { public_id: 'standard' },
  player_count: 4,
  flipper_count: 2,
  production_quantity: '4016',
};

describe('FeaturesEditor dirty-state contract', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    GET.mockImplementation(
      async (path: string, opts?: { params?: { query?: { type?: string; q?: string } } }) => {
        if (path === '/api/models/edit-options/') return EDIT_OPTIONS;
        if (path === '/api/field-constraints/{entity_type}') return FIELD_CONSTRAINTS;
        if (path === '/api/entity-autocomplete/') {
          const type = opts?.params?.query?.type;
          const q = (opts?.params?.query?.q ?? '').toLowerCase();
          const rows = type === 'theme' ? THEME_ROWS : GF_ROWS;
          const results = rows.filter((r) => r.label.toLowerCase().includes(q));
          return { data: { results }, error: undefined, response: { status: 200 } };
        }
        throw new Error(`Unexpected GET ${path}`);
      },
    );
  });

  it('shows Production quantity but not Game format (moved to Basics)', () => {
    render(FeaturesEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    expect(screen.getByLabelText('Production quantity')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Game format' })).toBeNull();
  });

  it('rejects save when a feature has a count but no slug', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(FeaturesEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    // Clear the gameplay feature slug (click the × button on that row's SearchableSelect)
    const gameplayFieldset = screen.getByRole('group', { name: 'Gameplay Features' });
    const clearBtn = within(gameplayFieldset).getByRole('button', { name: 'Clear selection' });
    await user.click(clearBtn);

    // The row now has count=3 but no slug — save should reject
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByTestId('last-error')).not.toHaveTextContent('');
    expect(PATCH).not.toHaveBeenCalled();
  });

  it('reports clean state initially and dirty state after editing', async () => {
    const user = userEvent.setup();
    render(FeaturesEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: '×' }));

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('changing only player_count PATCHes just that scalar, no M2Ms', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    const user = userEvent.setup();
    render(FeaturesEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    const playersInput = screen.getByLabelText('Players');
    await user.clear(playersInput);
    await user.type(playersInput, '6');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: { player_count: 6 }, note: '', citations: [] },
    });
  });

  it('changing only a theme PATCHes just themes, no scalars', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    const user = userEvent.setup();
    render(FeaturesEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    await user.click(screen.getByRole('combobox', { name: 'Themes' }));
    await user.click(await screen.findByRole('option', { name: 'Fantasy' }));

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { themes: ['medieval', 'fantasy'], note: '', citations: [] },
    });
  });
});
