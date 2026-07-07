import { fireEvent, render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import EditCitationField from './EditCitationField.svelte';
import EditCitationFieldFixture from './EditCitationField.fixture.svelte';

const { GET, POST } = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  default: { GET, POST },
}));

function getOpenCitationPickerButton() {
  return screen.getByRole('button', { name: /add citation/i });
}

/** The row for one attached citation, located by its source-name group label. */
function row(sourceName: string) {
  return within(screen.getByRole('group', { name: sourceName }));
}

describe('EditCitationField', () => {
  afterEach(() => {
    GET.mockReset();
    POST.mockReset();
  });

  it('adds a citation through the autocomplete flow and shows the mixed-edit warning', async () => {
    const user = userEvent.setup();
    GET.mockImplementation(async (path: string) => {
      if (path === '/api/citation-sources/search/') {
        return {
          data: {
            results: [
              {
                id: 7,
                name: 'Williams Flyer',
                source_type: 'web',
                author: '',
                publisher: '',
                year: 1993,
                isbn: null,
              },
            ],
            recognition: null,
          },
        };
      }
      return { data: [] };
    });
    POST.mockResolvedValue({
      data: {
        id: 42,
        citation_source_id: 7,
        citation_source_name: 'Williams Flyer',
        locator: 'p. 2',
        created_at: '2026-04-08T00:00:00Z',
      },
    });

    render(EditCitationField, { showMixedEditWarning: true });

    await user.click(getOpenCitationPickerButton());
    // The picker replaces the button that summoned it — no dead control above.
    expect(screen.queryByRole('button', { name: /add citation/i })).not.toBeInTheDocument();
    await user.type(screen.getByRole('combobox', { name: /search sources/i }), 'flyer');

    const sourceResult = await screen.findByRole('option', { name: /williams flyer/i });
    await fireEvent.pointerDown(sourceResult);
    await user.type(screen.getByRole('textbox', { name: /location in source/i }), 'p. 2');
    await fireEvent.pointerDown(screen.getByRole('button', { name: 'Insert' }));

    // A locator entered at the picker's own stage lands in the row's locator
    // field, editable until save.
    expect(await screen.findByText('Williams Flyer')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /location in source/i })).toHaveValue('p. 2');
    expect(
      screen.getByText(/This citation will apply to all changed fields in this save/i),
    ).toBeInTheDocument();
    // The list editor keeps inviting further sources.
    expect(screen.getByRole('button', { name: 'Add another citation' })).toBeInTheDocument();
  });

  it('stacks one row per citation and pluralizes the mixed-edit warning', () => {
    render(EditCitationFieldFixture);

    expect(screen.getByRole('group', { name: 'Williams Flyer' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Pinside thread' })).toBeInTheDocument();
    expect(
      screen.getByText(/These citations will apply to all changed fields in this save/i),
    ).toBeInTheDocument();
  });

  it('removes only the row whose Remove was clicked, writing through to the host', async () => {
    const user = userEvent.setup();
    render(EditCitationFieldFixture);

    await user.click(row('Williams Flyer').getByRole('button', { name: 'Remove' }));

    expect(screen.queryByRole('group', { name: 'Williams Flyer' })).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Pinside thread' })).toBeInTheDocument();
    expect(screen.getByTestId('citations-json')).not.toHaveTextContent('Williams Flyer');
  });

  it('binds each row quote to its own citation', async () => {
    const user = userEvent.setup();
    render(EditCitationFieldFixture);

    await user.type(
      row('Williams Flyer').getByRole('textbox', { name: /quote/i }),
      'Released in 1997.',
    );

    expect(row('Williams Flyer').getByRole('textbox', { name: /quote/i })).toHaveValue(
      'Released in 1997.',
    );
    expect(row('Pinside thread').getByRole('textbox', { name: /quote/i })).toHaveValue('');
    expect(screen.getByTestId('citations-json')).toHaveTextContent('Released in 1997.');
  });

  it('shows no rows or warning before a citation is selected', () => {
    render(EditCitationField, { citations: [], showMixedEditWarning: true });
    expect(screen.queryByRole('textbox', { name: /quote/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/will apply to all changed fields/i)).not.toBeInTheDocument();
    // Before any pick, the button doesn't yet say "another".
    expect(screen.getByRole('button', { name: 'Add citation' })).toBeInTheDocument();
  });
});
