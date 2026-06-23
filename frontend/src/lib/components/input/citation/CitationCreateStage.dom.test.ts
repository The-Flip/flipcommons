import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CitationCreateStage from './CitationCreateStage.svelte';
import { CREATED_SOURCE } from './citation-fixtures';

const { mockPOST } = vi.hoisted(() => ({ mockPOST: vi.fn() }));
vi.mock('$lib/api/client', () => ({ default: { POST: mockPOST } }));

const BOOK_PARENT = {
  id: 30,
  name: 'Learning Python',
  source_type: 'book',
  author: 'Mark Lutz',
  identifier_key: '',
};

function noop() {}

beforeEach(() => mockPOST.mockReset());

describe('CitationCreateStage', () => {
  it('creates a parentless book root via the type picker (no URL field — web is URL-only)', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Pinball Compendium' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // Books and magazines only — web sources are created by pasting a URL.
    expect(screen.getByRole('button', { name: 'book' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'magazine' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'web' })).not.toBeInTheDocument();
    // No URL field anywhere in this stage.
    expect(screen.queryByLabelText('URL')).not.toBeInTheDocument();

    // A non-web source advances to the locator next, so the button says "Continue".
    await user.click(screen.getByRole('button', { name: /Continue/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({
        name: 'Pinball Compendium',
        source_type: 'book',
        parent_id: null,
      }),
    });
  });

  it('creates an edition under a parent (type locked, linkless)', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: BOOK_PARENT,
      seed: { kind: 'name', name: 'Second Edition' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // A parent locks the type, so no picker.
    expect(screen.queryByRole('button', { name: 'book' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Continue/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({
        source_type: 'book',
        parent_id: BOOK_PARENT.id,
      }),
    });
  });

  it('an extraction (ISBN) draft prefills Publisher and Year; a manual name seed does not', () => {
    const { unmount } = render(CitationCreateStage, {
      parentContext: null,
      seed: {
        kind: 'extraction',
        draft: {
          name: 'Learning Python',
          source_type: 'book',
          author: 'Mark Lutz',
          publisher: "O'Reilly Media",
          year: 2009,
          isbn: '9780596517748',
        },
      },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    expect((screen.getByLabelText(/Author/) as HTMLInputElement).value).toBe('Mark Lutz');
    expect((screen.getByLabelText(/Publisher/) as HTMLInputElement).value).toBe("O'Reilly Media");
    expect((screen.getByLabelText(/Year/) as HTMLInputElement).value).toBe('2009');
    unmount();

    // A manual 'name' seed has no scraped metadata, so Publisher/Year are hidden.
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Manual Book' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.queryByLabelText(/Publisher/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Year/)).not.toBeInTheDocument();
  });
});
