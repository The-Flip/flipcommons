import { render, screen, fireEvent } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import MarkdownTextArea from './MarkdownTextArea.svelte';

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

function getTextarea() {
  return screen.getByRole('textbox', { name: /description/i }) as HTMLTextAreaElement;
}

function getToolbarButton(label: string) {
  return screen.getByRole('button', { name: label });
}

/** Set textarea value and selection, then click a toolbar button. */
async function applyToolbarAction(
  user: ReturnType<typeof userEvent.setup>,
  textarea: HTMLTextAreaElement,
  value: string,
  selStart: number,
  selEnd: number,
  buttonLabel: string,
) {
  textarea.value = value;
  textarea.selectionStart = selStart;
  textarea.selectionEnd = selEnd;
  await user.click(getToolbarButton(buttonLabel));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MarkdownToolbar', () => {
  it('renders all toolbar buttons', () => {
    renderTextArea();
    expect(getToolbarButton('Bold')).toBeInTheDocument();
    expect(getToolbarButton('Italic')).toBeInTheDocument();
    expect(getToolbarButton('Link')).toBeInTheDocument();
    expect(getToolbarButton('Bulleted list')).toBeInTheDocument();
    expect(getToolbarButton('Numbered list')).toBeInTheDocument();
    expect(getToolbarButton('Citation')).toBeInTheDocument();
  });

  it('has an accessible toolbar role', () => {
    renderTextArea();
    expect(screen.getByRole('toolbar', { name: /markdown formatting/i })).toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // Bold
  // -----------------------------------------------------------------------

  it('wraps selection with bold markers', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = getTextarea();

    await applyToolbarAction(user, textarea, 'hello world', 6, 11, 'Bold');
    expect(textarea).toHaveValue('hello **world**');
  });

  it('inserts empty bold markers with no selection', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = getTextarea();

    await applyToolbarAction(user, textarea, 'hello ', 6, 6, 'Bold');
    expect(textarea).toHaveValue('hello ****');
  });

  // -----------------------------------------------------------------------
  // Italic
  // -----------------------------------------------------------------------

  it('wraps selection with italic markers', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = getTextarea();

    await applyToolbarAction(user, textarea, 'hello world', 6, 11, 'Italic');
    expect(textarea).toHaveValue('hello *world*');
  });

  // -----------------------------------------------------------------------
  // Link
  // -----------------------------------------------------------------------

  it('opens the wikilink type picker when link is clicked', async () => {
    renderTextArea();
    const user = userEvent.setup();
    const textarea = getTextarea();

    textarea.focus();
    await user.click(getToolbarButton('Link'));

    await vi.waitFor(() => {
      expect(screen.getByText('Insert link')).toBeInTheDocument();
    });
  });

  // -----------------------------------------------------------------------
  // Bulleted list
  // -----------------------------------------------------------------------

  // -----------------------------------------------------------------------
  // Bulleted list
  // -----------------------------------------------------------------------

  it('adds bullet prefix to selected lines', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = getTextarea();

    await applyToolbarAction(user, textarea, 'alpha\nbeta', 0, 10, 'Bulleted list');
    expect(textarea).toHaveValue('- alpha\n- beta');
  });

  it('removes bullet prefix when already bulleted', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = getTextarea();

    await applyToolbarAction(user, textarea, '- alpha\n- beta', 0, 14, 'Bulleted list');
    expect(textarea).toHaveValue('alpha\nbeta');
  });

  // -----------------------------------------------------------------------
  // Numbered list
  // -----------------------------------------------------------------------

  it('adds numbered prefix to selected lines', async () => {
    const user = userEvent.setup();
    renderTextArea();
    const textarea = getTextarea();

    await applyToolbarAction(user, textarea, 'alpha\nbeta', 0, 10, 'Numbered list');
    expect(textarea).toHaveValue('1. alpha\n2. beta');
  });

  // -----------------------------------------------------------------------
  // Citation
  // -----------------------------------------------------------------------

  it('opens citation flow directly, skipping type picker', async () => {
    renderTextArea();
    const user = userEvent.setup();
    const textarea = getTextarea();

    textarea.focus();
    await user.click(getToolbarButton('Citation'));

    // Should skip the type picker ("Insert link") and go straight to citation
    await vi.waitFor(() => {
      expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
      expect(screen.getByText(/search.*source/i)).toBeInTheDocument();
    });
  });

  it('switches an open type-picker dropdown into the citation flow when Citation is clicked', async () => {
    renderTextArea();
    const user = userEvent.setup();
    const textarea = getTextarea();

    // Type `[[` to open the type picker (userEvent treats `[` as a key
    // descriptor, so set value + selection and fire `input` directly).
    textarea.focus();
    textarea.value = '[[';
    textarea.selectionStart = 2;
    textarea.selectionEnd = 2;
    fireEvent.input(textarea);

    await vi.waitFor(() => {
      expect(screen.getByText('Insert link')).toBeInTheDocument();
    });

    await user.click(getToolbarButton('Citation'));

    await vi.waitFor(() => {
      expect(screen.queryByText('Insert link')).not.toBeInTheDocument();
      expect(screen.getByText(/search.*source/i)).toBeInTheDocument();
    });
  });
});
