import { fireEvent, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import EditCitationField from './EditCitationField.svelte';

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

function getLocatorInput() {
  return screen.getByRole('textbox', { name: /citation locator/i });
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
    await user.type(screen.getByRole('combobox', { name: /search sources/i }), 'flyer');

    const sourceResult = await screen.findByRole('option', { name: /williams flyer/i });
    await fireEvent.pointerDown(sourceResult);
    await user.type(screen.getByRole('textbox', { name: /citation locator/i }), 'p. 2');
    await fireEvent.pointerDown(screen.getByRole('button', { name: 'Insert' }));

    // A locator entered at the picker's own stage lands in the panel's
    // locator field, editable until save.
    expect(await screen.findByText('Williams Flyer')).toBeInTheDocument();
    expect(getLocatorInput()).toHaveValue('p. 2');
    expect(
      screen.getByText(/This citation will apply to all changed fields in this save/i),
    ).toBeInTheDocument();
  });

  it('removes an existing citation selection', async () => {
    const user = userEvent.setup();

    render(EditCitationField, {
      citation: {
        citationSourceId: 7,
        sourceName: 'Williams Flyer',
        locator: 'p. 2',
        quote: '',
      },
    });

    expect(screen.getByText('Williams Flyer')).toBeInTheDocument();
    expect(getLocatorInput()).toHaveValue('p. 2');
    await user.click(screen.getByRole('button', { name: 'Remove citation' }));
    expect(screen.queryByText('Williams Flyer')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /citation locator/i })).not.toBeInTheDocument();
  });

  it('binds the quote textarea to the selected citation', async () => {
    const user = userEvent.setup();
    const citation = {
      citationSourceId: 7,
      sourceName: 'Williams Flyer',
      locator: 'p. 2',
      quote: '',
    };

    render(EditCitationField, { citation });

    const quoteInput = screen.getByRole('textbox', { name: /quote from the source/i });
    await user.type(quoteInput, 'Released in 1997.');
    expect(quoteInput).toHaveValue('Released in 1997.');
  });

  it('shows no quote textarea before a citation is selected', () => {
    render(EditCitationField, { citation: null });
    expect(
      screen.queryByRole('textbox', { name: /quote from the source/i }),
    ).not.toBeInTheDocument();
  });

  describe('the unprompted locator affordance', () => {
    const locatorlessCitation = {
      citationSourceId: 7,
      sourceName: 'Pinside thread',
      locator: '',
      quote: '',
    };

    it('collapses the locator behind "Add a locator" when the pick has none', () => {
      render(EditCitationField, { citation: { ...locatorlessCitation } });
      expect(screen.queryByRole('textbox', { name: /citation locator/i })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add a locator/i })).toBeInTheDocument();
    });

    it('expands to a focused freeform input that binds the locator', async () => {
      const user = userEvent.setup();
      render(EditCitationField, { citation: { ...locatorlessCitation } });

      await user.click(screen.getByRole('button', { name: /add a locator/i }));
      const input = getLocatorInput();
      expect(input).toHaveFocus();
      // The affordance is gone once the field is open.
      expect(screen.queryByRole('button', { name: /add a locator/i })).not.toBeInTheDocument();

      await user.type(input, '1:35');
      expect(input).toHaveValue('1:35');
    });

    it('keeps the field open when its text is cleared mid-edit', async () => {
      const user = userEvent.setup();
      render(EditCitationField, { citation: { ...locatorlessCitation } });

      await user.click(screen.getByRole('button', { name: /add a locator/i }));
      await user.type(getLocatorInput(), '1:35');
      await user.clear(getLocatorInput());
      expect(getLocatorInput()).toBeInTheDocument();
    });
  });
});
