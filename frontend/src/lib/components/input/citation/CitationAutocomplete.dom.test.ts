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

  render(CitationAutocomplete, {
    completion: { kind: 'mint-instance', oncomplete },
    oncancel,
    onback,
  });

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

function getLocatorInput() {
  return screen.getByRole('textbox', { name: /location in source/i }) as HTMLInputElement;
}

function getQuoteInput() {
  return screen.getByRole('textbox', { name: /quote/i }) as HTMLTextAreaElement;
}

/**
 * Navigate from search to the locator stage by selecting a non-abstract source.
 */
async function enterLocatorStage(user: ReturnType<typeof userEvent.setup>) {
  await searchAndWaitFor(user, 'pinball', MOCK_SOURCES[0]);
  await selectSource(MOCK_SOURCES[0]);

  await vi.waitFor(() => {
    expect(getLocatorInput()).toBeInTheDocument();
  });
}

/**
 * The inline flow always shows the refine screen — quote-only for
 * skip-locator sources — before minting. Complete it by skipping.
 */
async function skipQuoteScreen() {
  await vi.waitFor(() => {
    expect(screen.getByRole('button', { name: 'Skip' })).toBeInTheDocument();
  });
  fireEvent.pointerDown(screen.getByRole('button', { name: 'Skip' }));
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
      const nameInput = screen.getByLabelText('Name') as HTMLInputElement;
      nameInput.focus();
      await user.clear(nameInput);

      // Submit the form — type="submit" button requires click, not pointerDown
      await user.click(screen.getByRole('button', { name: /continue/i }));

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
      await user.click(screen.getByRole('button', { name: /continue/i }));

      await vi.waitFor(() => {
        expect(screen.getByText('Failed to create source.')).toBeInTheDocument();
      });

      // Retry: POST succeeds
      mockPOST
        .mockResolvedValueOnce({ data: CREATED_SOURCE })
        .mockResolvedValueOnce({ data: CREATED_INSTANCE });
      await user.click(screen.getByRole('button', { name: /continue/i }));

      // Error clears and flow continues (to locator, since CREATED_SOURCE has skip_locator: false)
      await vi.waitFor(() => {
        expect(screen.queryByText('Failed to create source.')).not.toBeInTheDocument();
        expect(getLocatorInput()).toBeInTheDocument();
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

      const locatorInput = getLocatorInput();
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

      const nameInput = screen.getByLabelText('Name');
      fireEvent.keyDown(nameInput, { key: 'Escape' });

      expect(oncancel).toHaveBeenCalledOnce();
    });

    it('fires oncancel on Escape from locator stage', async () => {
      const user = userEvent.setup();
      const { oncancel } = renderAutocomplete();

      await enterLocatorStage(user);

      const locatorInput = getLocatorInput();
      locatorInput.focus();
      fireEvent.keyDown(locatorInput, { key: 'Escape' });

      expect(oncancel).toHaveBeenCalledOnce();
    });

    it('fires oncancel on Escape from the quote textarea', async () => {
      const user = userEvent.setup();
      const { oncancel } = renderAutocomplete();

      await enterLocatorStage(user);

      const quoteInput = getQuoteInput();
      quoteInput.focus();
      fireEvent.keyDown(quoteInput, { key: 'Escape' });

      expect(oncancel).toHaveBeenCalledOnce();
    });
  });

  // -----------------------------------------------------------------------
  // Quote collection (inline flow)
  // -----------------------------------------------------------------------

  describe('quote collection', () => {
    it('sends the typed locator and quote in the mint POST', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      await enterLocatorStage(user);

      mockPOST.mockResolvedValueOnce({ data: CREATED_INSTANCE });

      const locatorInput = getLocatorInput();
      locatorInput.focus();
      await user.keyboard('p. 42');
      const quoteInput = getQuoteInput();
      quoteInput.focus();
      await user.keyboard('The flippers were revolutionary.');

      fireEvent.pointerDown(screen.getByRole('button', { name: 'Insert' }));

      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });
      expect(mockPOST).toHaveBeenCalledWith('/api/citation-instances/', {
        body: {
          citation_source_id: MOCK_SOURCES[0].id,
          locator: 'p. 42',
          quote: 'The flippers were revolutionary.',
        },
      });
    });

    it('Enter in the quote textarea inserts a newline instead of submitting', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      await enterLocatorStage(user);

      const quoteInput = getQuoteInput();
      quoteInput.focus();
      await user.keyboard('line one{Enter}line two');

      expect(quoteInput.value).toBe('line one\nline two');
      expect(mockPOST).not.toHaveBeenCalled();
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

      // skip_locator=true → the quote-only refine screen (no locator input),
      // then skipping completes the mint.
      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });
      expect(screen.queryByRole('textbox', { name: /location in source/i })).toBeNull();
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
        expect(screen.getByRole('button', { name: /Continue/ })).toBeInTheDocument();
      });

      // Click the recognition panel's quick-create button
      fireEvent.pointerDown(screen.getByRole('button', { name: /Continue/ }));

      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });

      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/{source_id}/records/', {
        params: { path: { source_id: IPDB_SOURCE.id } },
        body: { identifier: '9999' },
      });
    });

    it('domain-recognized URL → scrape → page step (Create Site skipped), page name prefilled', async () => {
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
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/') {
          return Promise.resolve({
            data: {
              draft: {
                name: 'Elton John',
                source_type: 'web',
                author: '',
                publisher: 'Jersey Jack',
                year: null,
                isbn: null,
                url: recognizedUrl,
              },
              match: null,
              error: null,
            },
          });
        }
        if (url === '/api/citation-sources/cite-url/') {
          return Promise.resolve({ data: { id: 31, name: recognizedUrl, skip_locator: true } });
        }
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard(recognizedUrl);

      await vi.waitFor(() => {
        // A domain match surfaces the recognized site, not a brand-new source.
        expect(screen.getByText(/Cite a page under/)).toBeInTheDocument();
        expect(screen.getByText(JJP_SOURCE.name)).toBeInTheDocument();
      });

      // Continue scrapes the page, then advances to the page step.
      fireEvent.pointerDown(screen.getByRole('button', { name: 'Continue' }));

      await vi.waitFor(() => {
        expect(screen.getByText('New page')).toBeInTheDocument();
      });
      // The site exists, so there's no Create Site panel; the page name is
      // prefilled from the scrape (the bug fix) and the URL carried in.
      expect(screen.queryByLabelText(/Site name/i)).not.toBeInTheDocument();
      expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('Elton John');
      expect((screen.getByLabelText('URL') as HTMLInputElement).value).toBe(recognizedUrl);

      await user.click(screen.getByRole('button', { name: /Continue/ }));

      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });

      // Routed through cite-url — which re-recognizes server-side and nests the
      // child under the existing root (site fields blank) — not a direct create.
      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/cite-url/', {
        body: { url: recognizedUrl, site_name: '', site_description: '', page_name: 'Elton John' },
      });
      expect(mockPOST).not.toHaveBeenCalledWith('/api/citation-sources/', expect.anything());
    });

    it('scheme-less domain-recognized URL carries the normalized URL through a failed scrape', async () => {
      // A scheme-less paste of a recognized domain behaves like the schemed one:
      // recognition fires (the normalized URL is sent to search). Here the scrape
      // fails, so the page step opens with a blank page name and the normalized URL.
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

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
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/') {
          return Promise.resolve({ data: { draft: null, match: null, error: 'timeout' } });
        }
        if (url === '/api/citation-sources/cite-url/') {
          return Promise.resolve({ data: { id: 31, name: 'x', skip_locator: true } });
        }
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('jerseyjackpinball.com/products/elton-john');

      await vi.waitFor(() => {
        expect(screen.getByText(/Cite a page under/)).toBeInTheDocument();
      });
      // No "Use this URL" — recognition took over, not the new-site extraction item.
      expect(screen.queryByRole('option', { name: /Use this URL/i })).not.toBeInTheDocument();

      fireEvent.pointerDown(screen.getByRole('button', { name: 'Continue' }));

      await vi.waitFor(() => {
        expect(screen.getByText('New page')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /Continue/ }));

      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });

      // cite-url receives the URL normalized to https://.
      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/cite-url/', {
        body: {
          url: 'https://jerseyjackpinball.com/products/elton-john',
          site_name: '',
          site_description: '',
          page_name: '',
        },
      });
    });
  });

  // -----------------------------------------------------------------------
  // Identify stage → create a page under a known web root (routes to web flow)
  // -----------------------------------------------------------------------

  describe('create a page under a known web root', () => {
    it('"+ Create" under a web root opens the web page step (not the authored-work form), page name prefilled', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      const jjpDetail = {
        id: JJP_SOURCE.id,
        name: JJP_SOURCE.name,
        source_type: 'web',
        author: '',
        publisher: '',
        year: null,
        month: null,
        day: null,
        date_note: '',
        isbn: null,
        description: '',
        identifier_key: '',
        skip_locator: false,
        parent: null,
        links: [],
        children: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };
      mockGET.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/search/') return mockSearchReturning([JJP_SOURCE]);
        if (url === '/api/citation-sources/{source_id}/')
          return Promise.resolve({ data: jjpDetail });
        if (url === '/api/citation-sources/{source_id}/children/')
          return Promise.resolve({ data: [] });
        return Promise.resolve({ data: [] });
      });

      // Search → select the abstract web root → identify stage ("Search pages…").
      await searchAndWaitFor(user, 'jersey', JJP_SOURCE);
      await selectSource(JJP_SOURCE);
      await vi.waitFor(() => {
        expect(screen.getByText(/No pages yet/)).toBeInTheDocument();
      });

      // Type a page title that matches nothing, then "+ Create".
      await user.keyboard('Elton John');
      fireEvent.pointerDown(screen.getByRole('option', { name: /Create "Elton John"/ }));

      // Routes to the web flow's page step — not the book/magazine form.
      await vi.waitFor(() => {
        expect(screen.getByText('New page')).toBeInTheDocument();
      });
      expect(screen.getByText(JJP_SOURCE.name)).toBeInTheDocument();
      expect(screen.queryByLabelText(/Site name/i)).not.toBeInTheDocument();
      // The typed text carries through as the page-name prefill.
      expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe('Elton John');
      const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
      expect(urlInput.value).toBe('');
      expect(urlInput.readOnly).toBe(false);

      // Finalize files the page DIRECTLY under the chosen root (the explicit
      // parent the user navigated into) via create_citation_source — not cite-url,
      // which would re-recognize the typed URL and could land it elsewhere.
      mockPOST
        .mockResolvedValueOnce({ data: { id: 31, name: 'Elton John', skip_locator: true } })
        .mockResolvedValueOnce({ data: CREATED_INSTANCE });
      await user.type(urlInput, 'https://jerseyjackpinball.com/products/elton-john');
      await user.click(screen.getByRole('button', { name: /Continue/ }));

      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });
      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/{source_id}/pages/', {
        params: { path: { source_id: JJP_SOURCE.id } },
        body: {
          url: 'https://jerseyjackpinball.com/products/elton-john',
          page_name: 'Elton John',
        },
      });
      expect(mockPOST).not.toHaveBeenCalledWith(
        '/api/citation-sources/cite-url/',
        expect.anything(),
      );
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
        expect(screen.getByText('Cite')).toBeInTheDocument();
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

      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });

      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/{source_id}/records/', {
        params: { path: { source_id: IPDB_SOURCE.id } },
        body: { identifier: '4443' },
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
        expect(getLocatorInput()).toBeInTheDocument();
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
      const authorInput = screen.getByLabelText(/author/i) as HTMLInputElement;
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
    it('shows "Use this URL" action and suppresses "+ Create" for URL input', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://en.wikipedia.org/wiki/Pinball');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Use this URL/i })).toBeInTheDocument();
      });
      // The generic "+ Create" is redundant for a URL — "Use this URL" already
      // advances to the create stage — so it must not appear.
      expect(screen.queryByRole('option', { name: /\+ Create/ })).not.toBeInTheDocument();
    });

    it('treats a scheme-less URL as a URL ("Use this URL", no "+ Create")', async () => {
      const user = userEvent.setup();
      renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));

      const input = getSearchInput();
      input.focus();
      await user.keyboard('www.imdb.com/title/tt27714946/');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Use this URL/i })).toBeInTheDocument();
      });
      expect(screen.queryByRole('option', { name: /\+ Create/ })).not.toBeInTheDocument();
    });

    it('URL lookup web draft → describe-site flow → finalize calls cite-url then the instance endpoint', async () => {
      const user = userEvent.setup();
      const { oncomplete } = renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: EXTRACT_URL_DRAFT });
        if (url === '/api/citation-sources/cite-url/')
          return Promise.resolve({
            data: { id: 99, name: 'Wikipedia', skip_locator: true },
          });
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://en.wikipedia.org/wiki/Pinball');

      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Use this URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Use this URL/i }));

      // Site panel: a one-time site-setup step, name prefilled from og:site_name.
      await vi.waitFor(() => {
        expect(screen.getByText('New site')).toBeInTheDocument();
      });
      expect((screen.getByLabelText(/Site name/i) as HTMLInputElement).value).toBe('Wikipedia');
      await user.click(screen.getByRole('button', { name: 'Next' }));

      // Page panel: page name prefilled from og:title, URL confirmed.
      expect((screen.getByLabelText(/Page name/i) as HTMLInputElement).value).toBe(
        'Pinball - Wikipedia',
      );
      expect((screen.getByLabelText('URL') as HTMLInputElement).value).toBe(
        'https://en.wikipedia.org/wiki/Pinball',
      );

      await user.click(screen.getByRole('button', { name: /Continue/ }));

      // Finalize fires cite-url, then the quote-only refine screen (the child
      // is skip_locator=true); skipping mints the instance — citing the child,
      // not a root.
      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });
      expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/cite-url/', {
        body: {
          url: 'https://en.wikipedia.org/wiki/Pinball',
          site_name: 'Wikipedia',
          site_description: '',
          page_name: 'Pinball - Wikipedia',
        },
      });
      expect(mockPOST).toHaveBeenCalledWith('/api/citation-instances/', {
        body: { citation_source_id: 99, locator: '', quote: '' },
      });
      // No bare-root create.
      expect(mockPOST).not.toHaveBeenCalledWith('/api/citation-sources/', expect.anything());
    });

    it('abandoning the describe-site flow before finalize issues no writes', async () => {
      const user = userEvent.setup();
      const { oncancel } = renderAutocomplete();

      mockGET.mockReturnValue(mockSearchReturning([]));
      mockPOST.mockImplementation((url: string) => {
        if (url === '/api/citation-sources/extract/')
          return Promise.resolve({ data: EXTRACT_URL_DRAFT });
        return Promise.resolve({ data: CREATED_INSTANCE });
      });

      const input = getSearchInput();
      input.focus();
      await user.keyboard('https://en.wikipedia.org/wiki/Pinball');
      await vi.waitFor(() => {
        expect(screen.getByRole('option', { name: /Use this URL/i })).toBeInTheDocument();
      });
      fireEvent.pointerDown(screen.getByRole('option', { name: /Use this URL/i }));
      await vi.waitFor(() => {
        expect(screen.getByText('New site')).toBeInTheDocument();
      });

      // Advance to the page panel, then bail out via Escape — nothing written.
      await user.click(screen.getByRole('button', { name: 'Next' }));
      await user.keyboard('{Escape}');

      expect(oncancel).toHaveBeenCalled();
      // Only the search GET and extract POST ran; no source/instance write.
      expect(mockPOST).not.toHaveBeenCalledWith(
        '/api/citation-sources/cite-url/',
        expect.anything(),
      );
      expect(mockPOST).not.toHaveBeenCalledWith('/api/citation-instances/', expect.anything());
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
        expect(screen.getByRole('option', { name: /Use this URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Use this URL/i }));

      // Match has skip_locator=true → quote-only refine screen, then complete
      await skipQuoteScreen();
      await vi.waitFor(() => {
        expect(oncomplete).toHaveBeenCalledWith(CREATED_INSTANCE);
      });
    });

    it('URL lookup error → describe-site flow as a web source, URL prefilled and editable', async () => {
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
        expect(screen.getByRole('option', { name: /Use this URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Use this URL/i }));

      // A failed scrape no longer dead-ends — it lands in the describe-site flow
      // (web-new-root), no error message.
      await vi.waitFor(() => {
        expect(screen.getByText('New site')).toBeInTheDocument();
      });
      expect(screen.queryByText(/timed out/i)).not.toBeInTheDocument();
      // Nothing scraped, so Site name prefills from the domain.
      expect((screen.getByLabelText(/Site name/i) as HTMLInputElement).value).toBe('example.com');
      await user.click(screen.getByRole('button', { name: 'Next' }));
      const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
      expect(urlInput.value).toBe('https://example.com/slow-page');
      // A failed scrape is exactly when the URL may be mistyped — it's editable.
      expect(urlInput.readOnly).toBe(false);
    });

    it('URL lookup blocked → dead-ends with a message, does NOT advance to create', async () => {
      // `blocked` is the SSRF guard (internal/disallowed host). Unlike a transient
      // failure, it must not funnel into a saved citation — it dead-ends instead.
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
        expect(screen.getByRole('option', { name: /Use this URL/i })).toBeInTheDocument();
      });

      fireEvent.pointerDown(screen.getByRole('option', { name: /Use this URL/i }));

      await vi.waitFor(() => {
        expect(screen.getByText(/can't be cited/i)).toBeInTheDocument();
      });
      // It must NOT have advanced to the create stage.
      expect(screen.queryByText('New source')).not.toBeInTheDocument();
    });
  });
});
