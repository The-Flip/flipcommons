import { render, screen, fireEvent, cleanup } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MarkdownTextArea from './MarkdownTextArea.svelte';
import {
  MOCK_SOURCES,
  CREATED_INSTANCE,
  ABSTRACT_BOOK_SOURCE,
  IPDB_SOURCE,
  IPDB_CHILD,
  BOOK_CHILDREN,
  BOOK_DETAIL_RESPONSE,
} from './citation/citation-fixtures';

vi.mock('$lib/api/link-types', async () => {
  const f = await import('./link-types-fixtures');
  return {
    fetchLinkTypes: vi.fn().mockResolvedValue(f.LINK_TYPES),
    searchLinkTargets: vi.fn().mockResolvedValue({ results: f.SEARCH_RESULTS }),
  };
});

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

function renderTextArea(label = 'Description') {
  return render(MarkdownTextArea, { label });
}

/**
 * Simulate typing `[[` into a textarea.
 *
 * userEvent treats `[` as a key-descriptor opener, so `[[` is its escape for
 * a single literal `[`. Instead of fighting the parser we set the value
 * directly and fire `input` — we're testing MarkdownTextArea's trigger
 * detection, not the browser's keypress pipeline.
 */
function typeWikilinkTrigger(textarea: HTMLTextAreaElement, prefix = '', suffix = '') {
  const triggerText = `${prefix}[[${suffix}`;
  const cursorPos = prefix.length + 2;

  textarea.focus();
  textarea.value = triggerText;
  textarea.selectionStart = cursorPos;
  textarea.selectionEnd = cursorPos;
  fireEvent.input(textarea);
}

/**
 * Send a keydown to the textarea without clicking it.
 *
 * Clicking the textarea would trigger handleTextareaClick which closes the
 * dropdown — so we fire the keydown event directly on the element.
 */
function sendTextareaKeydown(textarea: HTMLTextAreaElement, key: string) {
  fireEvent.keyDown(textarea, { key });
}

async function waitForTypePicker() {
  await vi.waitFor(() => {
    expect(screen.getByText('Insert link')).toBeInTheDocument();
  });
}

async function enterCitationFlow(
  textarea: HTMLTextAreaElement,
  prefix = '',
  suffix = '',
): Promise<HTMLInputElement> {
  typeWikilinkTrigger(textarea, prefix, suffix);
  await waitForTypePicker();

  sendTextareaKeydown(textarea, 'ArrowDown');
  sendTextareaKeydown(textarea, 'ArrowDown');
  sendTextareaKeydown(textarea, 'Enter');

  await vi.waitFor(() => {
    expect(screen.getByRole('combobox', { name: /search sources/i })).toBeInTheDocument();
  });

  return screen.getByRole('combobox', { name: /search sources/i }) as HTMLInputElement;
}

async function searchCitation(
  user: ReturnType<typeof userEvent.setup>,
  searchInput: HTMLInputElement,
  query = 'pinball',
) {
  searchInput.focus();
  await user.keyboard(query);

  await vi.waitFor(() => {
    expect(
      screen.getByRole('option', { name: new RegExp(MOCK_SOURCES[0].name) }),
    ).toBeInTheDocument();
  });
}

async function selectFirstCitationResult() {
  // DropdownItem uses onpointerdown (not onclick), so fire pointerDown directly
  // to avoid flaky timing with userEvent.click in jsdom.
  fireEvent.pointerDown(screen.getByRole('option', { name: new RegExp(MOCK_SOURCES[0].name) }));

  return (await screen.findByRole('textbox', {
    name: /citation locator/i,
  })) as HTMLInputElement;
}

function expectDropdownClosed() {
  expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
  expect(screen.queryByRole('combobox', { name: /search sources/i })).not.toBeInTheDocument();
}

/**
 * Navigate from the textarea into the book identify-by-search stage:
 * trigger [[ → type picker → Citation → search "pinball" → select abstract book → children load.
 */
async function enterBookIdentifyStage(
  user: ReturnType<typeof userEvent.setup>,
  textarea: HTMLTextAreaElement,
) {
  mockGET.mockImplementation((url: string) => {
    if (url === '/api/citation-sources/search/') {
      return Promise.resolve({ data: { results: [ABSTRACT_BOOK_SOURCE], recognition: null } });
    }
    if (url === '/api/citation-sources/{source_id}/') {
      return Promise.resolve({ data: BOOK_DETAIL_RESPONSE });
    }
    return Promise.resolve({ data: [] });
  });

  const searchInput = await enterCitationFlow(textarea);
  searchInput.focus();
  await user.keyboard('pinball');

  await vi.waitFor(() => {
    expect(
      screen.getByRole('option', { name: new RegExp(ABSTRACT_BOOK_SOURCE.name) }),
    ).toBeInTheDocument();
  });

  fireEvent.pointerDown(
    screen.getByRole('option', { name: new RegExp(ABSTRACT_BOOK_SOURCE.name) }),
  );

  // Wait for identify stage with children loaded
  await vi.waitFor(
    () => {
      expect(screen.getByText(ABSTRACT_BOOK_SOURCE.name)).toBeInTheDocument();
      expect(
        screen.getByRole('option', { name: new RegExp(BOOK_CHILDREN[0].name) }),
      ).toBeInTheDocument();
    },
    { timeout: 2000 },
  );
}

/**
 * Navigate from the textarea into the IPDB identify-by-search stage:
 * trigger [[ → type picker → Citation → search "IPDB" → select IPDB source → children load.
 */
async function enterIpdbIdentifyStage(
  user: ReturnType<typeof userEvent.setup>,
  textarea: HTMLTextAreaElement,
  childrenResponse: (typeof IPDB_CHILD)[],
) {
  const IPDB_DETAIL = {
    id: IPDB_SOURCE.id,
    name: IPDB_SOURCE.name,
    source_type: 'web',
    author: '',
    publisher: '',
    year: null,
    month: null,
    day: null,
    date_note: '',
    isbn: null,
    description: '',
    identifier_key: 'ipdb',
    skip_locator: false,
    parent: null,
    links: [],
    children: childrenResponse,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  };

  mockGET.mockImplementation((url: string) => {
    if (url === '/api/citation-sources/search/') {
      return Promise.resolve({ data: { results: [IPDB_SOURCE], recognition: null } });
    }
    if (url === '/api/citation-sources/{source_id}/') {
      return Promise.resolve({ data: IPDB_DETAIL });
    }
    if (url === '/api/citation-sources/{source_id}/children/') {
      return Promise.resolve({ data: childrenResponse });
    }
    return Promise.resolve({ data: [] });
  });

  const searchInput = await enterCitationFlow(textarea);
  searchInput.focus();
  await user.keyboard('IPDB');

  await vi.waitFor(() => {
    expect(screen.getByRole('option', { name: new RegExp(IPDB_SOURCE.name) })).toBeInTheDocument();
  });

  fireEvent.pointerDown(screen.getByRole('option', { name: new RegExp(IPDB_SOURCE.name) }));

  // Wait for identify stage (search_children) to load
  if (childrenResponse.length > 0) {
    await vi.waitFor(() => {
      expect(
        screen.getByRole('option', { name: new RegExp(childrenResponse[0].name) }),
      ).toBeInTheDocument();
    });
  } else {
    await vi.waitFor(() => {
      expect(screen.getByRole('combobox', { name: /search pages/i })).toBeInTheDocument();
    });
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MarkdownTextArea citation integration', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    mockGET.mockReset().mockResolvedValue({ data: { results: MOCK_SOURCES, recognition: null } });
    mockPOST.mockReset();
  });

  it('inserts a citation with a locator through the full textarea flow', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await enterCitationFlow(textarea, 'See ', ' after');
    await searchCitation(user, searchInput);
    const locatorInput = await selectFirstCitationResult();

    locatorInput.focus();
    await user.keyboard('p. 42');

    mockPOST.mockResolvedValueOnce({ data: CREATED_INSTANCE });
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Insert' }));

    const expectedCitation = `[[cite:${CREATED_INSTANCE.id}]]`;
    await vi.waitFor(() => {
      expect(textarea).toHaveValue(`See ${expectedCitation} after`);
    });

    expect(textarea.selectionStart).toBe('See '.length + expectedCitation.length);
    expect(textarea.selectionEnd).toBe('See '.length + expectedCitation.length);
    expect(document.activeElement).toBe(textarea);
    expectDropdownClosed();
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-instances/', {
      body: {
        citation_source_id: MOCK_SOURCES[0].id,
        locator: 'p. 42',
      },
    });
  });

  it('inserts a citation with an empty locator when skip is used', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await enterCitationFlow(textarea, 'Ref ');
    await searchCitation(user, searchInput);
    await selectFirstCitationResult();

    mockPOST.mockResolvedValueOnce({ data: CREATED_INSTANCE });
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Skip' }));

    await vi.waitFor(() => {
      expect(textarea).toHaveValue(`Ref [[cite:${CREATED_INSTANCE.id}]]`);
    });

    expect(document.activeElement).toBe(textarea);
    expectDropdownClosed();
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-instances/', {
      body: {
        citation_source_id: MOCK_SOURCES[0].id,
        locator: '',
      },
    });
  });

  it('allows text selection in dropdown inputs (mousedown is not prevented)', async () => {
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;
    const searchInput = await enterCitationFlow(textarea);

    // Mousedown on an input inside the dropdown should NOT be prevented
    // (allows click-to-place-cursor and click-drag-to-select-text)
    const inputEvent = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
    searchInput.dispatchEvent(inputEvent);
    expect(inputEvent.defaultPrevented).toBe(false);

    // Mousedown on a non-input element should still be prevented
    // (keeps focus on textarea, prevents blur)
    const header = document.querySelector('.dropdown-header')!;
    const headerEvent = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
    header.dispatchEvent(headerEvent);
    expect(headerEvent.defaultPrevented).toBe(true);
  });

  it('returns to the type picker and resumes textarea keyboard handling after citation back-navigation', async () => {
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await enterCitationFlow(textarea);

    searchInput.focus();
    fireEvent.keyDown(searchInput, { key: 'Backspace' });

    await vi.waitFor(() => {
      expect(screen.getByText('Insert link')).toBeInTheDocument();
    });

    expect(document.activeElement).toBe(textarea);

    sendTextareaKeydown(textarea, 'Escape');

    await vi.waitFor(() => {
      expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
    });
  });

  it('selects a book child from the identify stage and shows the locator', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    await enterBookIdentifyStage(user, textarea);

    // Should show children as selectable options
    expect(
      screen.getByRole('option', { name: new RegExp(BOOK_CHILDREN[0].name) }),
    ).toBeInTheDocument();

    // Select the first child edition
    fireEvent.pointerDown(screen.getByRole('option', { name: new RegExp(BOOK_CHILDREN[0].name) }));

    // Should transition to locator stage with the child's name in the header
    await vi.waitFor(() => {
      expect(screen.getByRole('textbox', { name: /citation locator/i })).toBeInTheDocument();
      expect(screen.getByText(`Citing: ${BOOK_CHILDREN[0].name}`)).toBeInTheDocument();
    });
  });

  it('IPDB source with skip_locator bypasses locator stage', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    await enterIpdbIdentifyStage(user, textarea, [IPDB_CHILD]);

    mockPOST.mockResolvedValueOnce({ data: CREATED_INSTANCE });

    // Select the child from the identify stage list
    fireEvent.pointerDown(screen.getByRole('option', { name: new RegExp(IPDB_CHILD.name) }));

    // skip_locator=true — citation inserted directly, no locator stage
    await vi.waitFor(() => {
      expect(textarea).toHaveValue(`[[cite:${CREATED_INSTANCE.id}]]`);
    });
    expect(screen.queryByRole('textbox', { name: /citation locator/i })).not.toBeInTheDocument();
    expectDropdownClosed();
  });

  it('auto-completes citation when recognized IPDB URL is pasted', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    // Mock: search returns recognition with existing child
    mockGET.mockImplementation((url: string) => {
      if (url === '/api/citation-sources/search/') {
        return Promise.resolve({
          data: {
            results: [IPDB_SOURCE],
            recognition: {
              parent: { id: IPDB_SOURCE.id, name: IPDB_SOURCE.name },
              child: { id: IPDB_CHILD.id, name: IPDB_CHILD.name, skip_locator: true },
              identifier: '4836',
            },
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    mockPOST.mockResolvedValueOnce({ data: CREATED_INSTANCE });

    // Enter citation flow and paste the IPDB URL
    const searchInput = await enterCitationFlow(textarea);
    searchInput.focus();
    await user.keyboard('https://www.ipdb.org/machine.cgi?id=4836');

    // The recognized child should appear with a Cite button
    await vi.waitFor(() => {
      expect(screen.getByText(IPDB_CHILD.name)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Cite' })).toBeInTheDocument();
    });

    // Click the Cite button — should auto-complete citation
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Cite' }));

    // Citation should be inserted directly — no identify stage, no manual clicks
    await vi.waitFor(() => {
      expect(textarea).toHaveValue(`[[cite:${CREATED_INSTANCE.id}]]`);
    });

    expectDropdownClosed();
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-instances/', {
      body: {
        citation_source_id: IPDB_CHILD.id,
        locator: '',
      },
    });
  });

  it('wires aria-activedescendant on the citation search combobox', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await enterCitationFlow(textarea);
    await searchCitation(user, searchInput);

    // Combobox should control a listbox
    const listboxId = searchInput.getAttribute('aria-controls');
    expect(listboxId).toBeTruthy();
    expect(document.getElementById(listboxId!)).toHaveAttribute('role', 'listbox');

    // No active descendant initially
    expect(searchInput).not.toHaveAttribute('aria-activedescendant');

    // ArrowDown highlights first result — read its id from the DOM
    fireEvent.keyDown(searchInput, { key: 'ArrowDown' });
    const options = screen.getAllByRole('option');
    expect(searchInput.getAttribute('aria-activedescendant')).toBe(options[0].id);

    // ArrowDown highlights second result
    fireEvent.keyDown(searchInput, { key: 'ArrowDown' });
    expect(searchInput.getAttribute('aria-activedescendant')).toBe(options[1].id);
  });

  it('wires aria-activedescendant on the identify-by-search combobox', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    await enterBookIdentifyStage(user, textarea);

    const searchInput = screen.getByRole('combobox', {
      name: /filter editions/i,
    }) as HTMLInputElement;

    // Combobox should control a listbox
    const listboxId = searchInput.getAttribute('aria-controls');
    expect(listboxId).toBeTruthy();
    expect(document.getElementById(listboxId!)).toHaveAttribute('role', 'listbox');

    // No active descendant initially
    expect(searchInput).not.toHaveAttribute('aria-activedescendant');

    // ArrowDown highlights first child edition
    searchInput.focus();
    fireEvent.keyDown(searchInput, { key: 'ArrowDown' });
    const options = screen.getAllByRole('option');
    expect(searchInput.getAttribute('aria-activedescendant')).toBe(options[0].id);

    // ArrowDown highlights second child edition
    fireEvent.keyDown(searchInput, { key: 'ArrowDown' });
    expect(searchInput.getAttribute('aria-activedescendant')).toBe(options[1].id);
  });

  it('does not let keydown events bubble out of the citation dropdown', async () => {
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await enterCitationFlow(textarea);

    const outerListener = vi.fn();
    document.addEventListener('keydown', outerListener);

    try {
      fireEvent.keyDown(searchInput, { key: 'ArrowDown' });
      fireEvent.keyDown(searchInput, { key: 'ArrowUp' });
      fireEvent.keyDown(searchInput, { key: 'Enter' });

      // The outer listener should NOT see these events — they are stopped
      // by the orchestrator's onkeydown stopPropagation
      expect(outerListener).not.toHaveBeenCalled();
    } finally {
      document.removeEventListener('keydown', outerListener);
    }
  });
});
