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
  },
};

const INITIAL_MODEL = {
  ipdb_id: 1521,
  opdb_id: 'mm',
  pinside_id: 'medieval-madness',
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

    expect(screen.getByTestId('dirty')).toHaveTextContent('false');

    const pinsideIdInput = screen.getByLabelText('Pinside ID');
    await user.clear(pinsideIdInput);
    await user.type(pinsideIdInput, 'mm-special');

    expect(screen.getByTestId('dirty')).toHaveTextContent('true');
  });
});
