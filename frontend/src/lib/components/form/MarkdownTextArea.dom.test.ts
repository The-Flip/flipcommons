import { render, screen, fireEvent } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import MarkdownTextArea from './MarkdownTextArea.svelte';
import { SEARCH_RESULTS } from './link-types-fixtures';

vi.mock('$lib/api/link-types', async () => {
  const f = await import('./link-types-fixtures');
  return {
    fetchLinkTypes: vi.fn().mockResolvedValue(f.LINK_TYPES),
    searchLinkTargets: vi.fn().mockResolvedValue({ results: f.SEARCH_RESULTS }),
  };
});

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
function typeWikilinkTrigger(textarea: HTMLTextAreaElement, prefix = '') {
  const text = prefix + '[[';
  textarea.focus();
  textarea.value = text;
  textarea.selectionStart = text.length;
  textarea.selectionEnd = text.length;
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

/** Wait for the wikilink dropdown type picker to appear. */
async function waitForDropdown() {
  await vi.waitFor(() => {
    expect(screen.getByText('Insert link')).toBeInTheDocument();
  });
}

/** Open dropdown and transition to search stage with results loaded. */
async function openSearchFromTextArea(textarea: HTMLTextAreaElement, prefix = '') {
  typeWikilinkTrigger(textarea, prefix);
  await waitForDropdown();

  sendTextareaKeydown(textarea, 'Enter');
  await vi.waitFor(() => {
    expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
  });

  await vi.waitFor(() => {
    expect(screen.getByText(SEARCH_RESULTS[0].label)).toBeInTheDocument();
  });

  const searchInput = screen.getByRole('combobox', { name: /search title/i });
  return searchInput;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MarkdownTextArea', () => {
  // -----------------------------------------------------------------------
  // Trigger detection
  // -----------------------------------------------------------------------

  it('opens the wikilink dropdown when [[ is typed', async () => {
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    typeWikilinkTrigger(textarea);
    await waitForDropdown();
  });

  it('does not open dropdown for a single [', async () => {
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    textarea.focus();
    textarea.value = '[';
    textarea.selectionStart = 1;
    textarea.selectionEnd = 1;
    fireEvent.input(textarea);

    // handleInput → detectTrigger is synchronous — no async work to wait for
    expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // Link insertion
  // -----------------------------------------------------------------------

  it('inserts a wikilink at the cursor position when a result is selected', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await openSearchFromTextArea(textarea, 'Hello ');

    await user.click(searchInput);
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');

    // Wikilink should be inserted, replacing the [[ trigger
    expect(textarea).toHaveValue(`Hello [[title:${SEARCH_RESULTS[0].ref}]]`);

    // Dropdown should be closed
    expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
  });

  it('positions cursor after the inserted link', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await openSearchFromTextArea(textarea, 'See ');

    await user.click(searchInput);
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');

    const expectedLink = `[[title:${SEARCH_RESULTS[0].ref}]]`;
    const expectedPos = 'See '.length + expectedLink.length;
    expect(textarea.selectionStart).toBe(expectedPos);
    expect(textarea.selectionEnd).toBe(expectedPos);
  });

  it('preserves text after cursor when trigger is mid-text', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    // Simulate typing [[ at position 6 in existing text
    textarea.focus();
    textarea.value = 'Link: [[ and more text';
    textarea.selectionStart = 8;
    textarea.selectionEnd = 8;
    fireEvent.input(textarea);

    await waitForDropdown();

    sendTextareaKeydown(textarea, 'Enter');
    await vi.waitFor(() => {
      expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
    });
    await vi.waitFor(() => {
      expect(screen.getByText(SEARCH_RESULTS[0].label)).toBeInTheDocument();
    });

    const searchInput = screen.getByRole('combobox', { name: /search title/i });
    await user.click(searchInput);
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');

    expect(textarea).toHaveValue(`Link: [[title:${SEARCH_RESULTS[0].ref}]] and more text`);
  });

  // -----------------------------------------------------------------------
  // Focus management
  // -----------------------------------------------------------------------

  it('keeps dropdown open when focus moves from textarea to autocomplete', async () => {
    vi.useFakeTimers();
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      renderTextArea();
      const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

      typeWikilinkTrigger(textarea);
      await waitForDropdown();

      // Transition to search stage so there's a focusable input inside the dropdown
      sendTextareaKeydown(textarea, 'Enter');
      await vi.waitFor(() => {
        expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
      });

      // Click search input — focus leaves textarea, blur fires with 150ms delay
      const searchInput = screen.getByRole('combobox', { name: /search title/i });
      await user.click(searchInput);

      // Advance past BLUR_DELAY_MS (150ms) so the blur handler runs
      await vi.advanceTimersByTimeAsync(200);

      // Dropdown should still be open — focus is within the autocomplete
      expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  // BUG REGRESSION: textarea focus must be restored after link insertion,
  // otherwise the user can't continue typing.
  it('returns focus to textarea after inserting a link', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await openSearchFromTextArea(textarea);

    // Focus is on search input
    await user.click(searchInput);
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');

    // Focus should return to the textarea
    expect(document.activeElement).toBe(textarea);
  });

  it('restores textarea focus on back-navigation so keyboard nav continues working', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    const searchInput = await openSearchFromTextArea(textarea);

    // Focus moves to search input
    await user.click(searchInput);

    // Back-navigate to type picker
    await user.keyboard('{Backspace}');

    // Focus should be back on the textarea
    expect(document.activeElement).toBe(textarea);

    // Keyboard nav should work — ArrowLeft on type picker closes the dropdown
    sendTextareaKeydown(textarea, 'ArrowLeft');
    expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // Close behavior
  // -----------------------------------------------------------------------

  it('closes the dropdown on click outside', async () => {
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    typeWikilinkTrigger(textarea);
    await waitForDropdown();

    // Fire pointerdown outside the wrapper (the $effect handler listens in capture phase)
    fireEvent.pointerDown(document.body);

    await vi.waitFor(() => {
      expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
    });
  });

  it('closes the dropdown when textarea is clicked', async () => {
    renderTextArea();
    const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

    typeWikilinkTrigger(textarea);
    await waitForDropdown();

    // handleTextareaClick closes the dropdown
    fireEvent.click(textarea);

    await vi.waitFor(() => {
      expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
    });
  });

  it('cleans up deferred focus and blur timers on unmount', async () => {
    vi.useFakeTimers();
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const rendered = renderTextArea();
      const textarea = screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;

      typeWikilinkTrigger(textarea);
      await waitForDropdown();

      sendTextareaKeydown(textarea, 'Enter');
      await vi.advanceTimersByTimeAsync(0);
      await vi.waitFor(() => {
        expect(screen.getByRole('combobox', { name: /search title/i })).toBeInTheDocument();
      });

      const searchInput = screen.getByRole('combobox', { name: /search title/i });
      await user.click(searchInput);

      rendered.unmount();

      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
