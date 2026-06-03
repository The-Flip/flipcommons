import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SystemTechnologyEditorFixture from './SystemTechnologyEditor.fixture.svelte';

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

const SUBGENS = {
  data: [
    { slug: 'discrete', name: 'Discrete', display_order: 0 },
    { slug: 'integrated', name: 'Integrated', display_order: 1 },
    { slug: 'pc-based', name: 'PC-Based', display_order: 2 },
  ],
};

const INITIAL = {
  technology_subgeneration: { public_id: 'integrated' },
};

function mockGetResponses() {
  GET.mockImplementation(async (path: string) => {
    if (path === '/api/technology-subgenerations/') return SUBGENS;
    throw new Error(`Unexpected GET ${path}`);
  });
}

describe('SystemTechnologyEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockGetResponses();
  });

  it('reports clean state initially', async () => {
    const user = userEvent.setup();
    render(SystemTechnologyEditorFixture, { props: { initialData: INITIAL } });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');
  });

  it('does not PATCH when saving a clean form', async () => {
    const user = userEvent.setup();
    render(SystemTechnologyEditorFixture, { props: { initialData: INITIAL } });

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).not.toHaveBeenCalled();
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });
});
