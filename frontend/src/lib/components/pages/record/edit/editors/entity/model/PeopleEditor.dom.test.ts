import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { CreditSchema } from '$lib/api/schema';

import PeopleEditorFixture from './PeopleEditor.fixture.svelte';

type Credit = CreditSchema;

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
    people: [
      { slug: 'pat-lawlor', label: 'Pat Lawlor' },
      { slug: 'john-youssi', label: 'John Youssi' },
      { slug: 'mark-ritchie', label: 'Mark Ritchie' },
    ],
    credit_roles: [
      { slug: 'game-design', label: 'Game Design' },
      { slug: 'artwork', label: 'Artwork' },
      { slug: 'mechanical-design', label: 'Mechanical Design' },
    ],
  },
};

function makeCredit(
  personSlug: string,
  personName: string,
  role: string,
  roleDisplay: string,
): Credit {
  return {
    person: { public_id: personSlug, name: personName },
    role,
    role_display: roleDisplay,
    role_sort_order: 0,
  };
}

function renderEditor(credits: Credit[] = []) {
  GET.mockResolvedValue(EDIT_OPTIONS);
  return render(PeopleEditorFixture, {
    props: { initialData: credits, slug: 'medieval-madness' },
  });
}

describe('PeopleEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    PATCH.mockReset();
    invalidateAll.mockReset();
  });

  it('renders existing credits as rows', async () => {
    renderEditor([makeCredit('pat-lawlor', 'Pat Lawlor', 'game-design', 'Game Design')]);

    // The remove button should be present for the existing credit
    const removeButtons = screen.getAllByRole('button', { name: '×' });
    expect(removeButtons).toHaveLength(1);
  });

  it('"Add credit" button adds a new row', async () => {
    const user = userEvent.setup();
    renderEditor();

    const addButton = screen.getByRole('button', { name: 'Add credit' });
    await user.click(addButton);

    // Should now have one remove button (one row)
    const removeButtons = screen.getAllByRole('button', { name: '×' });
    expect(removeButtons).toHaveLength(1);
  });

  it('"Add credit" is disabled when a row has empty person or role', async () => {
    const user = userEvent.setup();
    renderEditor();

    const addButton = screen.getByRole('button', { name: 'Add credit' });

    // Add an empty row
    await user.click(addButton);

    // Button should now be disabled because the new row is incomplete
    expect(addButton).toBeDisabled();
  });

  it('remove button removes the correct row', async () => {
    renderEditor([
      makeCredit('pat-lawlor', 'Pat Lawlor', 'game-design', 'Game Design'),
      makeCredit('john-youssi', 'John Youssi', 'artwork', 'Artwork'),
    ]);

    const user = userEvent.setup();
    const removeButtons = screen.getAllByRole('button', { name: '×' });
    expect(removeButtons).toHaveLength(2);

    // Remove the first credit
    await user.click(removeButtons[0]);

    // Should have one row left
    const remaining = screen.getAllByRole('button', { name: '×' });
    expect(remaining).toHaveLength(1);
  });

  it('reports dirty state when an incomplete placeholder row is added', async () => {
    const user = userEvent.setup();
    renderEditor();

    expect(screen.getByTestId('dirty')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Add credit' }));

    expect(screen.getByTestId('dirty')).toHaveTextContent('true');
  });

  it('save() with no changes calls onsaved without PATCHing', async () => {
    const user = userEvent.setup();
    renderEditor([makeCredit('pat-lawlor', 'Pat Lawlor', 'game-design', 'Game Design')]);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
    expect(PATCH).not.toHaveBeenCalled();
  });

  it('selecting a different person shows the new label, not the stale one', async () => {
    const user = userEvent.setup();
    GET.mockImplementation(async (path: string, opts?: { params?: { query?: { q?: string } } }) => {
      if (path === '/api/models/edit-options/') return EDIT_OPTIONS;
      if (path === '/api/entity-autocomplete/') {
        const q = (opts?.params?.query?.q ?? '').toLowerCase();
        const rows = [
          { value: 'pat-lawlor', label: 'Pat Lawlor', sublabel: null },
          { value: 'john-youssi', label: 'John Youssi', sublabel: null },
        ].filter((r) => r.label.toLowerCase().includes(q));
        return { data: { results: rows }, error: undefined, response: { status: 200 } };
      }
      throw new Error(`Unexpected GET ${path}`);
    });
    render(PeopleEditorFixture, {
      props: {
        initialData: [makeCredit('pat-lawlor', 'Pat Lawlor', 'game-design', 'Game Design')],
        slug: 'medieval-madness',
      },
    });

    const personInput = screen.getByPlaceholderText('Search people...');
    expect(personInput).toHaveValue('Pat Lawlor');

    await user.click(personInput);
    await user.click(await screen.findByRole('option', { name: 'John Youssi' }));

    // The row's frozen `initial` must not re-seed the stale 'Pat Lawlor' label
    // over the freshly-selected one.
    expect(personInput).toHaveValue('John Youssi');
  });

  it('save() with changes calls PATCH with cleaned credits', async () => {
    const user = userEvent.setup();
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    renderEditor([
      makeCredit('pat-lawlor', 'Pat Lawlor', 'game-design', 'Game Design'),
      makeCredit('john-youssi', 'John Youssi', 'artwork', 'Artwork'),
    ]);

    // Remove one credit to create a change
    const removeButtons = screen.getAllByRole('button', { name: '×' });
    await user.click(removeButtons[1]);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(PATCH).toHaveBeenCalledOnce();
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });
});
