import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TitleExternalDataEditorFixture from './TitleExternalDataEditor.fixture.svelte';

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
    fandom_page_id: { min: 1, step: 1 },
  },
};

const INITIAL_TITLE = {
  opdb_id: 'G5pe4',
  fandom_page_id: 1234,
};

describe('TitleExternalDataEditor dirty-state contract', () => {
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
    render(TitleExternalDataEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    const opdbInput = screen.getByLabelText('OPDB Group ID');
    await user.clear(opdbInput);
    await user.type(opdbInput, 'G9abc');

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('PATCHes /api/titles/{public_id}/claims/ with only the changed field', async () => {
    const user = userEvent.setup();
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);
    render(TitleExternalDataEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    const opdbInput = screen.getByLabelText('OPDB Group ID');
    await user.clear(opdbInput);
    await user.type(opdbInput, 'G9abc');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(PATCH).toHaveBeenCalledWith('/api/titles/{public_id}/claims/', {
      params: { path: { public_id: 'addams-family' } },
      body: { fields: { opdb_id: 'G9abc' }, note: '' },
    });
  });
});
