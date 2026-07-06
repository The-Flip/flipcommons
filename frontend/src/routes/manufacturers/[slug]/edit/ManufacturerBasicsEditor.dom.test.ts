import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ManufacturerBasicsEditorFixture from './ManufacturerBasicsEditor.fixture.svelte';

const { PATCH } = vi.hoisted(() => ({
  PATCH: vi.fn(),
}));

const { invalidateAll } = vi.hoisted(() => ({
  invalidateAll: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  default: { PATCH },
}));

vi.mock('$app/navigation', () => ({
  invalidateAll,
}));

describe('ManufacturerBasicsEditor dirty-state contract', () => {
  beforeEach(() => {
    PATCH.mockReset();
    invalidateAll.mockReset();
  });

  it('reports clean state initially and dirty state after editing', async () => {
    const user = userEvent.setup();
    render(ManufacturerBasicsEditorFixture);

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    await user.clear(screen.getByLabelText('Website'));

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('PATCHes cleared nullable URL fields as null', async () => {
    PATCH.mockResolvedValueOnce({ data: { slug: 'williams' }, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(ManufacturerBasicsEditorFixture);

    await user.clear(screen.getByLabelText('Website'));
    await user.clear(screen.getByLabelText('Logo URL'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledWith('/api/manufacturers/{public_id}/claims/', {
      params: { path: { public_id: 'williams' } },
      body: {
        fields: { website: null, logo_url: null },
        note: '',
        citations: [],
        inline_citations: [],
      },
    });
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });
});
