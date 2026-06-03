import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import BasicsEditorFixture from './BasicsEditor.fixture.svelte';

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
    corporate_entities: [
      { slug: 'williams-electronics', label: 'Williams Electronics' },
      { slug: 'stern-pinball-inc', label: 'Stern Pinball, Inc.' },
    ],
    titles: [
      { slug: 'medieval-madness', label: 'Medieval Madness' },
      { slug: 'attack-from-mars', label: 'Attack from Mars' },
    ],
  },
};

const FIELD_CONSTRAINTS = {
  data: {
    year: { min: 1930, max: 2100, step: 1 },
  },
};

const INITIAL_MODEL = {
  year: 1997,
  month: 6,
  title: { public_id: 'medieval-madness' },
  corporate_entity: { public_id: 'williams-electronics' },
};

function mockGetResponses() {
  GET.mockImplementation(async (path: string) => {
    if (path === '/api/models/edit-options/') return EDIT_OPTIONS;
    if (path === '/api/field-constraints/{entity_type}') return FIELD_CONSTRAINTS;
    throw new Error(`Unexpected GET ${path}`);
  });
}

describe('BasicsEditor dirty-state contract', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockGetResponses();
  });

  it('reports clean state initially and dirty after editing year', async () => {
    const user = userEvent.setup();
    render(BasicsEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    const yearInput = screen.getByLabelText('Year');
    await user.clear(yearInput);
    await user.type(yearInput, '1998');

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('changing Title marks dirty and PATCHes only the title slug', async () => {
    const user = userEvent.setup();
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);
    render(BasicsEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    await user.click(screen.getByRole('combobox', { name: 'Title' }));
    await user.click(await screen.findByRole('option', { name: 'Attack from Mars' }));

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: { title: 'attack-from-mars' }, note: '' },
    });
  });

  it('PATCHes only the changed year', async () => {
    const user = userEvent.setup();
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);
    render(BasicsEditorFixture, {
      props: { initialData: INITIAL_MODEL },
    });

    const yearInput = screen.getByLabelText('Year');
    await user.clear(yearInput);
    await user.type(yearInput, '1998');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: { year: 1998 }, note: '' },
    });
  });
});

describe('BasicsEditor slim mode', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
    mockGetResponses();
  });

  it('hides the Title picker when slim', () => {
    render(BasicsEditorFixture, {
      props: { initialData: INITIAL_MODEL, slim: true },
    });

    expect(screen.queryByRole('combobox', { name: 'Title' })).toBeNull();

    // The kept fields are still rendered.
    expect(screen.getByRole('combobox', { name: 'Manufacturer' })).toBeInTheDocument();
    expect(screen.getByLabelText('Year')).toBeInTheDocument();
    expect(screen.getByLabelText('Month')).toBeInTheDocument();
  });
});
