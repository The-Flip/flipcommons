import { render, screen } from '@testing-library/svelte';
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

const MANUFACTURERS = {
  data: [
    { slug: 'williams', name: 'Williams', model_count: 50 },
    { slug: 'stern', name: 'Stern', model_count: 80 },
  ],
};

const INITIAL = {
  manufacturer: { public_id: 'williams' },
};

function mockGetResponses() {
  GET.mockImplementation(async (path: string) => {
    if (path === '/api/manufacturers/all/') return MANUFACTURERS;
    throw new Error(`Unexpected GET ${path}`);
  });
}

describe('SystemManufacturerEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockGetResponses();
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
});
