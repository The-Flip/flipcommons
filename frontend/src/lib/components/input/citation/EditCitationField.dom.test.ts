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
      if (path === '/api/citation-instances/batch/') {
        return {
          data: [
            {
              id: 42,
              source_name: 'Williams Flyer',
              source_type: 'web',
              author: '',
              year: 1993,
              locator: 'p. 2',
              links: [],
            },
          ],
        };
      }
      return { data: [] };
    });
    POST.mockResolvedValue({
      data: {
        id: 42,
        citation_source_id: 7,
        citation_source_name: 'Williams Flyer',
        claim_id: null,
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

    expect(await screen.findByText('Williams Flyer, p. 2')).toBeInTheDocument();
    expect(
      screen.getByText(/This citation will apply to all changed fields in this save/i),
    ).toBeInTheDocument();
  });

  it('removes an existing citation selection', async () => {
    const user = userEvent.setup();

    render(EditCitationField, {
      citation: {
        citationInstanceId: 42,
        sourceName: 'Williams Flyer',
        locator: 'p. 2',
      },
    });

    expect(screen.getByText('Williams Flyer, p. 2')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove citation' }));
    expect(screen.queryByText('Williams Flyer, p. 2')).not.toBeInTheDocument();
  });

  it('shows an error when the selected citation cannot be loaded', async () => {
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
      throw new Error('network failed');
    });
    POST.mockResolvedValue({
      data: {
        id: 42,
        citation_source_id: 7,
        citation_source_name: 'Williams Flyer',
        claim_id: null,
        locator: 'p. 2',
        created_at: '2026-04-08T00:00:00Z',
      },
    });

    render(EditCitationField);

    await user.click(getOpenCitationPickerButton());
    await user.type(screen.getByRole('combobox', { name: /search sources/i }), 'flyer');
    await fireEvent.pointerDown(await screen.findByRole('option', { name: /williams flyer/i }));
    await user.type(screen.getByRole('textbox', { name: /citation locator/i }), 'p. 2');
    await fireEvent.pointerDown(screen.getByRole('button', { name: 'Insert' }));

    expect(await screen.findByText('Failed to load citation.')).toBeInTheDocument();
    expect(screen.queryByText('Williams Flyer, p. 2')).not.toBeInTheDocument();
  });
});
