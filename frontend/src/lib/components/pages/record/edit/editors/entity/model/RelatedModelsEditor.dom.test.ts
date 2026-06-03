import { render, screen } from '@testing-library/svelte';
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

const EDIT_OPTIONS = {
  data: {
    models: [
      { slug: 'medieval-madness', label: 'Medieval Madness' },
      { slug: 'attack-from-mars', label: 'Attack from Mars' },
      { slug: 'monster-bash', label: 'Monster Bash' },
    ],
  },
};

describe('RelatedModelsEditor dirty-state contract', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    GET.mockImplementation(async (path: string) => {
      if (path === '/api/models/edit-options/') return EDIT_OPTIONS;
      throw new Error(`Unexpected GET ${path}`);
    });
  });

  it('reports clean state initially and dirty state after editing', async () => {
    const user = userEvent.setup();
    render(RelatedModelsEditorFixture, {
      props: {
        initialData: {
          variant_of: null,
          converted_from: null,
          remake_of: null,
        },
      },
    });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    await user.click(screen.getByRole('combobox', { name: 'Variant of' }));
    await user.click(await screen.findByRole('option', { name: 'Attack from Mars' }));

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });
});
