import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TitleFranchiseEditorFixture from './TitleFranchiseEditor.fixture.svelte';

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

const FRANCHISES = {
  data: [
    { slug: 'addams-family', name: 'Addams Family', title_count: 2 },
    { slug: 'star-wars', name: 'Star Wars', title_count: 5 },
  ],
};

const SERIES = {
  data: [{ slug: 'addams-series', name: 'Addams Series', title_count: 2 }],
};

const INITIAL_TITLE = {
  franchise: { public_id: 'addams-family' },
  series: null,
};

function mockGetResponses() {
  GET.mockImplementation(async (path: string) => {
    if (path === '/api/franchises/all/') return FRANCHISES;
    if (path === '/api/series/') return SERIES;
    throw new Error(`Unexpected GET ${path}`);
  });
}

describe('TitleFranchiseEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockGetResponses();
  });

  it('reports clean state initially', async () => {
    const user = userEvent.setup();
    render(TitleFranchiseEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');
  });

  it('does not PATCH when saving a clean form', async () => {
    const user = userEvent.setup();
    render(TitleFranchiseEditorFixture, {
      props: { initialData: INITIAL_TITLE },
    });

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).not.toHaveBeenCalled();
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });
});
