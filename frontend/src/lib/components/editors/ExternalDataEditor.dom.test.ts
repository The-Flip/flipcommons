import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ExternalDataEditorFixture from './ExternalDataEditor.fixture.svelte';

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

const FIELD_CONSTRAINTS = {
  data: {
    ipdb_id: { min: 1, max: 999999, step: 1 },
    ipdb_rating: { min: 1, max: 10, step: 0.1 },
    pinside_rating: { min: 1, max: 10, step: 0.1 },
  },
};

const INITIAL_MODEL = {
  ipdb_id: 1521,
  opdb_id: 'mm',
  pinside_id: 'medieval-madness',
  ipdb_rating: 8.3,
  pinside_rating: 8.7,
};

describe('ExternalDataEditor dirty-state contract', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    GET.mockImplementation(async (path: string) => {
      if (path === '/api/field-constraints/{entity_type}') return FIELD_CONSTRAINTS;
      throw new Error(`Unexpected GET ${path}`);
    });
  });

  it('reports clean state initially and dirty state after editing', async () => {
    const user = userEvent.setup();
    render(ExternalDataEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    const ipdbRatingInput = screen.getByLabelText('IPDB rating');
    await user.clear(ipdbRatingInput);
    await user.type(ipdbRatingInput, '9.1');

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });
});
