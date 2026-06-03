import { render, screen, fireEvent } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CitationAutocomplete from './CitationAutocomplete.svelte';
import {
  MOCK_SOURCES,
  CREATED_INSTANCE,
  CREATED_IPDB_CHILD,
  ABSTRACT_BOOK_SOURCE,
  IPDB_SOURCE,
  IPDB_CHILD,
  IPDB_DETAIL_RESPONSE,
  JJP_SOURCE,
  BOOK_CHILDREN,
  BOOK_DETAIL_RESPONSE,
  CREATED_SOURCE,
  EXTRACT_ISBN_DRAFT,
  EXTRACT_ISBN_MATCH,
  EXTRACT_URL_DRAFT,
  EXTRACT_URL_MATCH,
  EXTRACT_URL_BLOCKED,
} from './citation-fixtures';

const { mockGET, mockPOST } = vi.hoisted(() => ({
  mockGET: vi.fn(),
  mockPOST: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  default: { GET: mockGET, POST: mockPOST },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderAutocomplete() {
  const oncomplete = vi.fn();
  const oncancel = vi.fn();
  const onback = vi.fn();

  render(CitationAutocomplete, { oncomplete, oncancel, onback });

  return { oncomplete, oncancel, onback };
}

function getSearchInput() {
  return screen.getByRole('combobox', { name: /search sources/i }) as HTMLInputElement;
}

/** Default search mock: returns MOCK_SOURCES wrapped in CitationSourceSearchResponseSchema. */
function mockSearchReturning(results: typeof MOCK_SOURCES, recognition: unknown = null) {
  return Promise.resolve({ data: { results, recognition } });
}

async function searchAndWaitFor(
  user: ReturnType<typeof userEvent.setup>,
  query: string,
  source: { name: string },
) {
  const input = getSearchInput();
  input.focus();
  await user.keyboard(query);

  await vi.waitFor(() => {
    expect(screen.getByRole('option', { name: new RegExp(source.name) })).toBeInTheDocument();
  });

  return input;
}

async function selectSource(source: { name: string }) {
  fireEvent.pointerDown(screen.getByRole('option', { name: new RegExp(source.name) }));
}

/**
 * Navigate from search to the book identify-by-search stage:
 * search → select abstract book → children load.
 */
async function enterBookIdentifyStage(user: ReturnType<typeof userEvent.setup>) {
  mockGET.mockImplementation((url: string) => {
    if (url === '/api/citation-sources/search/') return mockSearchReturning([ABSTRACT_BOOK_SOURCE]);
    if (url === '/api/citation-sources/{source_id}/')
      return Promise.resolve({ data: BOOK_DETAIL_RESPONSE });
    return Promise.resolve({ data: [] });
  });

  await searchAndWaitFor(user, 'pinball', ABSTRACT_BOOK_SOURCE);
  await selectSource(ABSTRACT_BOOK_SOURCE);

  await vi.waitFor(() => {
    expect(
      screen.getByRole('option', { name: new RegExp(BOOK_CHILDREN[0].name) }),
    ).toBeInTheDocument();
  });
}

/**
 * Navigate from search to the create stage via "Create new".
 */
async function enterCreateStage(user: ReturnType<typeof userEvent.setup>, query = 'New Book') {
  await searchAndWaitFor(user, query, MOCK_SOURCES[0]);
  fireEvent.pointerDown(screen.getByRole('option', { name: new RegExp(`Create "${query}"`) }));

  await vi.waitFor(() => {
    expect(screen.getByText('New source')).toBeInTheDocument();
  });
}

/**
 * Navigate from search to the locator stage by selecting a non-abstract source.
 */
async function enterLocatorStage(user: ReturnType<typeof userEvent.setup>) {
  await searchAndWaitFor(user, 'pinball', MOCK_SOURCES[0]);
  await selectSource(MOCK_SOURCES[0]);

  await vi.waitFor(() => {
    expect(screen.getByRole('textbox', { name: /citation locator/i })).toBeInTheDocument();
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CitationAutocomplete (component-level)', () => {
  beforeEach(() => {
    mockGET.mockReset().mockImplementation((url: string) => {
      if (url === '/api/citation-sources/search/') return mockSearchReturning(MOCK_SOURCES);
      return Promise.resolve({ data: [] });
    });
    mockPOST.mockReset();
  });

  // -----------------------------------------------------------------------
  // Error and retry paths
  // -----------------------------------------------------------------------

  describe('error and retry paths', () => {
    it('shows validation error when submitting create stage with empty name', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      await enterCreateStage(user);

      // Clear the pre-filled name
      const nameInput = screen.getByPlaceholderText('Name') as HTMLInputElement;
      nameInput.focus();
      await user.clear(nameInput);

      // Submit the form — type="submit" button requires click, not pointerDown
      await user.click(screen.getByRole('button', { name: /create & cite/i }));

      await vi.waitFor(() => {
        expect(screen.getByText('Name is required.')).toBeInTheDocument();
      });
    });

    it('shows error on create stage POST failure and allows retry', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      await enterCreateStage(user, 'Test Source');

      // First attempt: POST fails (non-string error triggers generic message)
      mockPOST.mockResolvedValueOnce({ error: { detail: 'Server error' } });
      await user.click(screen.getByRole('button', { name: /create & cite/i }));

      await vi.waitFor(() => {
        expect(screen.getByText('Failed to create source.')).toBeInTheDocument();
      });

      // Retry: POST succeeds
      mockPOST
        .mockResolvedValueOnce({ data: CREATED_SOURCE })
        .mockResolvedValueOnce({ data: CREATED_INSTANCE });
      await user.click(screen.getByRole('button', { name: /create & cite/i }));

      // Error clears and flow continues (to locator, since CREATED_SOURCE has skip_locator: false)
      await vi.waitFor(() => {
        expect(screen.queryByText('Failed to create source.')).not.toBeInTheDocument();
        expect(screen.getByRole('textbox', { name: /citation locator/i })).toBeInTheDocument();
      });
    });

    it('shows error when citation instance POST fails at locator stage', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      await enterLocatorStage(user);

      // POST fails
      mockPOST.mockResolvedValueOnce({ error: 'Server error' });
      fireEvent.pointerDown(screen.getByRole('button', { name: 'Insert' }));

      await vi.waitFor(() => {
        expect(screen.getByText('Failed to create citation.')).toBeInTheDocument();
      });
    });
  });

  // -----------------------------------------------------------------------
  // Back / cancel behavior
  // -----------------------------------------------------------------------

  describe('back and cancel behavior', () => {
    it('fires onback when backing out of search stage', () => {
      const { onback } = renderAutocomplete();
      const input = getSearchInput();

      input.focus();
      fireEvent.keyDown(input, { key: 'Backspace' });

      expect(onback).toHaveBeenCalledOnce();
    });

    it('returns to search when backing out of identify stage', async () => {
      const user = userEvent.setup();
      const { onback } = renderAutocomplete();

      await enterBookIdentifyStage(user);

      // Back from identify → should return to search, not fire onback
      const filterInput = screen.getByRole('combobox', { name: /filter editions/i });
      filterInput.focus();
      fireEvent.keyDown(filterInput, { key: 'Backspace' });

      await vi.waitFor(() => {
        expect(getSearchInput()).toBeInTheDocument();
      });
      expect(onback).not.toHaveBeenCalled();
    });

    it('returns to search when backing out of create stage', async () => {
      const user = userEvent.setup();
      const { onback } = renderAutocomplete();

      await enterCreateStage(user);

      // DropdownHeader back button
      fireEvent.pointerDown(screen.getByRole('button', { name: /back/i }));

      await vi.waitFor(() => {
        expect(getSearchInput()).toBeInTheDocument();
      });
      expect(onback).not.toHaveBeenCalled();
    });

    it('returns to search when backing out of locator stage', async () => {
      const user = userEvent.setup();
      const { onback } = renderAutocomplete();

      await enterLocatorStage(user);

      const locatorInput = screen.getByRole('textbox', { name: /citation locator/i });
      locatorInput.focus();
      fireEvent.keyDown(locatorInput, { key: 'Backspace' });

      await vi.waitFor(() => {
        expect(getSearchInput()).toBeInTheDocument();
      });
      expect(onback).not.toHaveBeenCalled();
    });

    it('fires oncancel on Escape from search stage', () => {
      const { oncancel } = renderAutocomplete();
      const input = getSearchInput();

      input.focus();
      fireEvent.keyDown(input, { key: 'Escape' });

      expect(oncancel).toHaveBeenCalledOnce();
    });

    it('fires oncancel on Escape from identify stage', async () => {
      const user = userEvent.setup();
      const { oncancel } = renderAutocomplete();

      await enterBookIdentifyStage(user);

      const filterInput = screen.getByRole('combobox', { name: /filter editions/i });
      filterInput.focus();
      fireEvent.keyDown(filterInput, { key: 'Escape' });

      expect(oncancel).toHaveBeenCalledOnce();
    });

    it('fires oncancel on Escape from create stage', async () => {
      const user = userEvent.setup();
      const { oncancel } = renderAutocomplete();

      await enterCreateStage(user);

      const nameInput = screen.getByPlaceholderText('Name');
      fireEvent.keyDown(nameInput, { key: 'Escape' });

      expect(oncancel).toHaveBeenCalledOnce();
    });

    it('fires oncancel on Escape from locator stage', async () => {
      const user = userEvent.setup();
      const { oncancel } = renderAutocomplete();

      await enterLocatorStage(user);

      const locatorInput = screen.getByRole('textbox', { name: /citation locator/i });
      locatorInput.focus();
      fireEvent.keyDown(locatorInput, { key: 'Escape' });

      expect(oncancel).toHaveBeenCalledOnce();
    });
  });

  // -----------------------------------------------------------------------
  // Orchestrator guards
  // -----------------------------------------------------------------------

  describe('orchestrator guards', () => {
    it('prevents duplicate citation submission on rapid double-click', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      await enterLocatorStage(user);

      // Mock a POST that resolves slowly
      let resolvePost!: (value: { data: typeof CREATED_INSTANCE }) => void;
      const slowPost = new Promise<{ data: typeof CREATED_INSTANCE }>((resolve) => {
        resolvePost = resolve;
      });
      mockPOST.mockReturnValue(slowPost);

      const insertBtn = screen.getByRole('button', { name: 'Insert' });
      fireEvent.pointerDown(insertBtn);
      fireEvent.pointerDown(insertBtn);

      resolvePost({ data: CREATED_INSTANCE });

      await vi.waitFor(() => {
        expect(mockPOST).toHaveBeenCalledTimes(1);
      });
    });
  });

  // -----------------------------------------------------------------------
  // Recognition flows (backend-driven)
  // -----------------------------------------------------------------------

  describe('recognition flows', () => {
    it('shows exact match when recognition returns existing child', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      mockGET.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/search/') {
          return mockSearchReturning([IPDB_SOURCE], {
            parent: { id: IPDB_SOURCE.id, name: IPDB_SOURCE.name },
            child: {
              id: IPDB_CHILD.id,
              name: IPDB_CHILD.name,
              skip_locator: true,
            },
            identifier: '4836',
          });
        }
        return Promise.resolve({ data: [] });
      });
      mockPOST.mockResolvedValueOnce({ data: CREATED_INSTANCE });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://www.ipdb.org/machine.cgi?id=4836');

      await vi.waitFor(() => {
        expect(screen.getByText(IPDB_CHILD.name)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Cite' })).toBeInTheDocument();
      });

      // Click the Cite button
      fireEvent.pointerDown(screen.getByRole('button', { name: 'Cite' }));

      // Should auto-complete (skip_locator=true for web children)
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(`[[cite:${CREATED_INSTANCE.id}]]`);
      });
    });

    it('creates child when recognition returns identifier but no child', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      mockGET.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/search/') {
          return mockSearchReturning([IPDB_SOURCE], {
            parent: { id: IPDB_SOURCE.id, name: IPDB_SOURCE.name },
            child: null,
            identifier: '9999',
          });
        }
        return Promise.resolve({ data: [] });
      });
      mockPOST
        .mockResolvedValueOnce({ data: CREATED_IPDB_CHILD })
        .mockResolvedValueOnce({ data: CREATED_INSTANCE });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://www.ipdb.org/machine.cgi?id=9999');

      await vi.waitFor(() => {
        expect(screen.getByText(/Internet Pinball Database #9999/)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Create & cite/ })).toBeInTheDocument();
      });

      // Click the "Create & cite" button
      fireEvent.pointerDown(screen.getByRole('button', { name: /Create & cite/ }));

      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(`[[cite:${CREATED_INSTANCE.id}]]`);
      });

      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
        body: expect.objectContaining({
          parent_id: IPDB_SOURCE.id,
          identifier: '9999',
        }),
      });
    });

    it('creates child source when domain-recognized URL is pasted', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      const recognizedUrl = 'https://jerseyjackpinball.com/products/elton-john';

      mockGET.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/search/') {
          return mockSearchReturning([], {
            parent: { id: JJP_SOURCE.id, name: JJP_SOURCE.name },
            child: null,
            identifier: null,
          });
        }
        return Promise.resolve({ data: [] });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard(recognizedUrl);

      await vi.waitFor(() => {
        expect(screen.getByText(recognizedUrl)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Create & cite/ })).toBeInTheDocument();
      });

      mockPOST
        .mockResolvedValueOnce({
          data: { id: 31, name: recognizedUrl, skip_locator: true },
        })
        .mockResolvedValueOnce({ data: CREATED_INSTANCE });

      fireEvent.pointerDown(screen.getByRole('button', { name: /Create & cite/ }));

      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(`[[cite:${CREATED_INSTANCE.id}]]`);
      });

      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
        body: expect.objectContaining({
          parent_id: JJP_SOURCE.id,
          url: recognizedUrl,
        }),
      });
    });
  });

  // -----------------------------------------------------------------------
  // Identify stage: quick create and error handling
  // -----------------------------------------------------------------------

  describe('identify stage quick create', () => {
    /**
     * Navigate from search to the IPDB identify stage:
     * search "IPDB" → select abstract parent → children load (empty).
     */
    async function enterIpdbIdentifyStage(user: ReturnType<typeof userEvent.setup>) {
      mockGET.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/search/') return mockSearchReturning([IPDB_SOURCE]);
        if (url === '/api/citation-sources/{source_id}/')
          return Promise.resolve({ data: IPDB_DETAIL_RESPONSE });
        if (url === '/api/citation-sources/{source_id}/children/')
          return Promise.resolve({ data: [] });
        return Promise.resolve({ data: [] });
      });

      await searchAndWaitFor(user, 'IPDB', IPDB_SOURCE);
      await selectSource(IPDB_SOURCE);

      await vi.waitFor(() => {
        expect(screen.getByRole('combobox', { name: /search pages/i })).toBeInTheDocument();
      });

      return screen.getByRole('combobox', { name: /search pages/i }) as HTMLInputElement;
    }

    it('offers quick create for valid identifier under identifier-backed parent', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      const filterInput = await enterIpdbIdentifyStage(user);
      filterInput.focus();
      await user.keyboard('4443');

      await vi.waitFor(() => {
        expect(
          screen.getByRole('option', { name: /Internet Pinball Database #4443/ }),
        ).toBeInTheDocument();
        expect(screen.getByText('Create & cite')).toBeInTheDocument();
      });

      // No generic create should appear alongside quick create
      expect(screen.queryByRole('option', { name: /\+ Create/ })).not.toBeInTheDocument();
    });

    it('quick create with valid identifier succeeds and completes citation', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      const filterInput = await enterIpdbIdentifyStage(user);
      filterInput.focus();
      await user.keyboard('4443');

      await vi.waitFor(() => {
        expect(
          screen.getByRole('option', { name: /Internet Pinball Database #4443/ }),
        ).toBeInTheDocument();
      });

      mockPOST
        .mockResolvedValueOnce({ data: CREATED_IPDB_CHILD })
        .mockResolvedValueOnce({ data: CREATED_INSTANCE });

      fireEvent.pointerDown(
        screen.getByRole('option', { name: /Internet Pinball Database #4443/ }),
      );

      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(`[[cite:${CREATED_INSTANCE.id}]]`);
      });

      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
        body: expect.objectContaining({
          parent_id: IPDB_SOURCE.id,
          identifier: '4443',
        }),
      });
    });

    it('shows error and generic create fallback when quick create is rejected', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      const filterInput = await enterIpdbIdentifyStage(user);
      filterInput.focus();
      await user.keyboard('abc');

      await vi.waitFor(() => {
        expect(
          screen.getByRole('option', { name: /Internet Pinball Database #abc/ }),
        ).toBeInTheDocument();
      });

      // Backend rejects invalid identifier
      mockPOST.mockResolvedValueOnce({ error: 'Invalid identifier for IPDB' });
      fireEvent.pointerDown(screen.getByRole('option', { name: /Internet Pinball Database #abc/ }));

      await vi.waitFor(() => {
        // Error message should be visible
        expect(screen.getByText(/Invalid identifier/i)).toBeInTheDocument();
        // Quick create item should be hidden
        expect(
          screen.queryByRole('option', { name: /Internet Pinball Database #abc/ }),
        ).not.toBeInTheDocument();
        // Generic create should appear as fallback
        expect(screen.getByRole('option', { name: /\+ Create "abc"/ })).toBeInTheDocument();
      });
    });

    it('clears error when user types new input after rejected quick create', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      const filterInput = await enterIpdbIdentifyStage(user);
      filterInput.focus();
      await user.keyboard('abc');

      await vi.waitFor(() => {
        expect(
          screen.getByRole('option', { name: /Internet Pinball Database #abc/ }),
        ).toBeInTheDocument();
      });

      // Trigger rejection
      mockPOST.mockResolvedValueOnce({ error: 'Invalid identifier for IPDB' });
      fireEvent.pointerDown(screen.getByRole('option', { name: /Internet Pinball Database #abc/ }));

      await vi.waitFor(() => {
        expect(screen.getByText(/Invalid identifier/i)).toBeInTheDocument();
      });

      // Type new input — error should clear
      await user.keyboard('4443');

      await vi.waitFor(() => {
        expect(screen.queryByText(/Invalid identifier/i)).not.toBeInTheDocument();
        expect(
          screen.getByRole('option', { name: /Internet Pinball Database #abc4443/ }),
        ).toBeInTheDocument();
      });
    });

    it('does not offer generic create when recognition is present', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/search/') {
          return mockSearchReturning([IPDB_SOURCE], {
            parent: { id: IPDB_SOURCE.id, name: IPDB_SOURCE.name },
            child: {
              id: IPDB_CHILD.id,
              name: IPDB_CHILD.name,
              skip_locator: true,
            },
            identifier: '4836',
          });
        }
        return Promise.resolve({ data: [] });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://www.ipdb.org/machine.cgi?id=4836');

      await vi.waitFor(() => {
        expect(screen.getByText(IPDB_CHILD.name)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Cite' })).toBeInTheDocument();
      });

      // No "Create" option should appear when recognition is present
      expect(screen.queryByRole('option', { name: /Create/ })).not.toBeInTheDocument();
    });
  });

  // -----------------------------------------------------------------------
  // ISBN extraction flows
  // -----------------------------------------------------------------------

  describe('ISBN extraction flows', () => {
    it('shows "Look up ISBN" action when ISBN-shaped input has no matches', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));

      const input = getSearchInput();
      input.focus();
      await user.keyboard('978-0-596-51774-8');

      await vi.waitFor(() => {
        expect(
          screen.getByRole('option', { name: /Look up ISBN 9780596517748/i }),
        ).toBeInTheDocument();
      });
    });

    it('ISBN lookup returns draft → create stage prefilled', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: EXTRACT_ISBN_DRAFT });
        if (url === '/api/citation-sources/') return Promise.resolve({ data: CREATED_SOURCE });
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('978-0-596-51774-8');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up ISBN/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up ISBN/i }));

      await vi.waitFor(() => {
        expect(screen.getByText('New source')).toBeInTheDocument();
      });

      // Verify prefilled fields
      expect(screen.getByDisplayValue('Learning Python')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Mark Lutz')).toBeInTheDocument();
      expect(screen.getByDisplayValue("O'Reilly Media")).toBeInTheDocument();
      expect(screen.getByDisplayValue('2009')).toBeInTheDocument();
      // Type picker should be hidden (locked to book)
      expect(screen.queryByText('magazine')).not.toBeInTheDocument();
    });

    it('ISBN lookup returns match → locator stage', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: EXTRACT_ISBN_MATCH });
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('978-0-596-51774-8');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up ISBN/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up ISBN/i }));

      // Match path → locator stage (source has skip_locator: false, so locator input appears)
      await vi.waitFor(() => {
        expect(screen.getByRole('textbox', { name: /citation locator/i })).toBeInTheDocument();
      });
    });

    it('ISBN lookup with empty author → create stage with empty editable author field', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      const draftNoAuthor = {
        ...EXTRACT_ISBN_DRAFT,
        draft: { ...EXTRACT_ISBN_DRAFT.draft, author: '' },
      };

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: draftNoAuthor });
        return Promise.resolve({ data: CREATED_SOURCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('978-0-596-51774-8');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up ISBN/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up ISBN/i }));

      await vi.waitFor(() => {
        expect(screen.getByText('New source')).toBeInTheDocument();
      });

      // Author field present and empty (editable)
      const authorInput = screen.getByPlaceholderText('Author (optional)') as HTMLInputElement;
      expect(authorInput.value).toBe('');
    });

    it('ISBN lookup error → shows error, Create fallback still available', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      const errorResponse = {
        draft: null,
        match: null,
        error: 'timeout',
        confidence: '',
        source_api: '',
      };

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: errorResponse });
        return Promise.resolve({ data: CREATED_SOURCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('978-0-596-51774-8');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up ISBN/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up ISBN/i }));

      await vi.waitFor(() => {
        expect(screen.getByText(/timed out/i)).toBeInTheDocument();
      });

      // Create fallback still available
      expect(screen.getByRole('option', { name: /Create/i })).toBeInTheDocument();
    });
  });

  // -----------------------------------------------------------------------
  // URL extraction flows
  // -----------------------------------------------------------------------

  describe('URL extraction flows', () => {
    it('shows "Look up URL" action when URL-shaped input has no matches', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://en.wikipedia.org/wiki/Pinball');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up URL/i })).toBeInTheDocument();
      });
    });

    it('URL lookup returns draft → create stage with URL pre-filled and scrape note', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: EXTRACT_URL_DRAFT });
        if (url === '/api/citation-sources/') return Promise.resolve({ data: CREATED_SOURCE });
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://en.wikipedia.org/wiki/Pinball');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up URL/i }));

      await vi.waitFor(() => {
        expect(screen.getByText('New source')).toBeInTheDocument();
      });

      // Verify prefilled fields
      expect(screen.getByDisplayValue('Pinball - Wikipedia')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Wikipedia')).toBeInTheDocument();
      expect(screen.getByDisplayValue('https://en.wikipedia.org/wiki/Pinball')).toBeInTheDocument();
      // Scrape note visible
      expect(screen.getByText(/Scraped from page/i)).toBeInTheDocument();
      // Type picker should be hidden (locked to web)
      expect(screen.queryByText('book')).not.toBeInTheDocument();
    });

    it('URL lookup returns match → auto-completes (skip_locator)', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: EXTRACT_URL_MATCH });
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://www.ipdb.org/machine.cgi?id=4836');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up URL/i }));

      // Match has skip_locator=true → auto-completes citation
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(`[[cite:${CREATED_INSTANCE.id}]]`);
      });
    });

    it('URL lookup error → error message with Create fallback', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      const errorResponse = {
        draft: null,
        match: null,
        error: 'timeout',
        confidence: '',
        source_api: '',
      };

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: errorResponse });
        return Promise.resolve({ data: CREATED_SOURCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://example.com/slow-page');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up URL/i }));

      await vi.waitFor(() => {
        expect(screen.getByText(/timed out/i)).toBeInTheDocument();
      });

      // Create fallback still available
      expect(screen.getByRole('option', { name: /Create/i })).toBeInTheDocument();
    });

    it('URL lookup blocked → "URL not allowed" error message', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: EXTRACT_URL_BLOCKED });
        return Promise.resolve({ data: CREATED_SOURCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('http://localhost:8000/admin/');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Look up URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Look up URL/i }));

      await vi.waitFor(() => {
        expect(screen.getByText(/URL not allowed/i)).toBeInTheDocument();
      });
    });
  });
});
