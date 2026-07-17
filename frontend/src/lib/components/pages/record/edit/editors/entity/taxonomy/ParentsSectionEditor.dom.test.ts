import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ParentsSectionEditorFixture from './ParentsSectionEditor.fixture.svelte';

const { GET } = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock('$lib/api/client', () => ({
  default: { GET },
}));

// The parent picker is a typeahead over /api/entity-autocomplete/; the current
// entity (`pop-bumper`) is filtered client-side via the widget's `exclude` prop.
const PARENT_ROWS = [
  { value: 'pop-bumper', label: 'Pop Bumper', sublabel: null },
  { value: 'physical-feature', label: 'Physical Feature', sublabel: null },
  { value: 'spinner', label: 'Spinner', sublabel: null },
];

describe('ParentsSectionEditor', () => {
  beforeEach(() => {
    GET.mockReset();
    GET.mockImplementation(async (path: string, opts?: { params?: { query?: { q?: string } } }) => {
      if (path === '/api/entity-autocomplete/') {
        const q = (opts?.params?.query?.q ?? '').toLowerCase();
        const results = PARENT_ROWS.filter((r) => r.label.toLowerCase().includes(q));
        return { data: { results }, error: undefined, response: { status: 200 } };
      }
      throw new Error(`Unexpected GET ${path}`);
    });
  });

  it('reports clean state initially', async () => {
    render(ParentsSectionEditorFixture);

    expect(screen.getByTestId('dirty')).toHaveTextContent('false');
  });

  it('filters the entity itself out of the loaded options', async () => {
    const user = userEvent.setup();
    render(ParentsSectionEditorFixture);

    // Wait for options to load
    await waitFor(() => {
      expect(screen.getByLabelText('Parents')).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText('Parents'));

    // pop-bumper is the entity's own slug — must not appear as a selectable option
    await waitFor(() => {
      expect(screen.queryByRole('option', { name: /Pop Bumper/i })).toBeNull();
    });
    expect(screen.getByRole('option', { name: /Physical Feature/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Spinner/i })).toBeInTheDocument();
  });

  it('reports dirty after adding a parent', async () => {
    const user = userEvent.setup();
    render(ParentsSectionEditorFixture);

    await waitFor(() => screen.getByLabelText('Parents'));
    await user.click(screen.getByLabelText('Parents'));
    await user.click(await screen.findByRole('option', { name: /Spinner/i }));

    expect(screen.getByTestId('dirty')).toHaveTextContent('true');
  });

  it('reports dirty after removing the original parent', async () => {
    const user = userEvent.setup();
    render(ParentsSectionEditorFixture);

    await waitFor(() => screen.getByLabelText('Parents'));
    await user.click(screen.getByRole('button', { name: 'Remove Physical Feature' }));

    expect(screen.getByTestId('dirty')).toHaveTextContent('true');
  });

  it('sends parent slugs in the save body when dirty', async () => {
    const user = userEvent.setup();
    render(ParentsSectionEditorFixture);

    await waitFor(() => screen.getByLabelText('Parents'));
    await user.click(screen.getByLabelText('Parents'));
    await user.click(await screen.findByRole('option', { name: /Spinner/i }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({ parents: ['physical-feature', 'spinner'] }),
    );
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('skips the save call when clean', async () => {
    const user = userEvent.setup();
    render(ParentsSectionEditorFixture);

    await waitFor(() => screen.getByLabelText('Parents'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent('null');
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('surfaces a 422 cycle error as a parents field error', async () => {
    const user = userEvent.setup();
    render(ParentsSectionEditorFixture, {
      props: {
        saveResult: {
          ok: false,
          error: 'parents: would create a cycle',
          fieldErrors: { parents: 'would create a cycle' },
        },
      },
    });

    await waitFor(() => screen.getByLabelText('Parents'));
    await user.click(screen.getByLabelText('Parents'));
    await user.click(await screen.findByRole('option', { name: /Spinner/i }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-error')).toHaveTextContent('Please fix the errors below.');
    expect(screen.getByRole('alert')).toHaveTextContent('would create a cycle');
  });

  it('surfaces a non-field error when no fieldErrors are returned', async () => {
    const user = userEvent.setup();
    render(ParentsSectionEditorFixture, {
      props: {
        saveResult: {
          ok: false,
          error: 'server exploded',
          fieldErrors: {},
        },
      },
    });

    await waitFor(() => screen.getByLabelText('Parents'));
    await user.click(screen.getByLabelText('Parents'));
    await user.click(await screen.findByRole('option', { name: /Spinner/i }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-error')).toHaveTextContent('server exploded');
  });
});
