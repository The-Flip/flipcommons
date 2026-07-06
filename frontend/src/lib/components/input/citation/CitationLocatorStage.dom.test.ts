import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import CitationLocatorStage from './CitationLocatorStage.svelte';
import type { CitationInstanceDraft } from './citation-types';

function noop() {}

function makeDraft(overrides: Partial<CitationInstanceDraft> = {}): CitationInstanceDraft {
  return {
    sourceId: 1,
    sourceName: 'Test Source',
    sourceType: 'book',
    locator: '',
    locatorHint: '',
    skipLocator: false,
    quote: '',
    ...overrides,
  };
}

describe('CitationLocatorStage', () => {
  it('shows the freeform label, hint and placeholder for a book', () => {
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'book' }),
      onsubmit: noop,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.getByRole('textbox', { name: /location in source/i })).toHaveAttribute(
      'placeholder',
      'p. 42, Chapter 3, timestamp...',
    );
    expect(screen.getByText('e.g. p. 42, Chapter 3, a timestamp')).toBeInTheDocument();
  });

  it('shows the timestamp label, hint and placeholder for a video', () => {
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'video' }),
      onsubmit: noop,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.getByRole('textbox', { name: /start time/i })).toHaveAttribute(
      'placeholder',
      'e.g. 1:02:03',
    );
    expect(
      screen.getByText('Where to begin watching — e.g. 1:02:03, 95, or 1h2m3s'),
    ).toBeInTheDocument();
  });

  it('prefills the input from the locator hint but requires confirmation', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'video', locatorHint: '1:35' }),
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    const input = screen.getByRole('textbox');
    expect(input).toHaveValue('1:35');
    expect(onsubmit).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Insert' }));
    expect(onsubmit).toHaveBeenCalledWith('1:35', '');
  });

  it('normalizes a video locator to the canonical form on submit', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'video' }),
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    await user.type(screen.getByRole('textbox'), '1h2m3s{Enter}');
    expect(onsubmit).toHaveBeenCalledWith('1:02:03', '');
  });

  it('blocks an invalid video locator and shows the type message', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'video' }),
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    await user.type(screen.getByRole('textbox'), 'p. 42{Enter}');
    expect(onsubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/start time/);
    // Typing again clears the error.
    await user.type(screen.getByRole('textbox'), '5');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('accepts any text for a freeform type', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'book' }),
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    await user.type(screen.getByRole('textbox'), 'p. 42{Enter}');
    expect(onsubmit).toHaveBeenCalledWith('p. 42', '');
  });

  it('skip always submits an empty locator and quote, even for video', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'video', locatorHint: '1:35' }),
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    expect(onsubmit).toHaveBeenCalledWith('', '');
  });

  it('shows no quote textarea by default (edit flow)', () => {
    render(CitationLocatorStage, {
      draft: makeDraft(),
      onsubmit: noop,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.queryByRole('textbox', { name: /quote/i })).toBeNull();
  });

  it('showQuote renders the quote textarea and submits its trimmed value', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'book' }),
      showQuote: true,
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    await user.type(screen.getByRole('textbox', { name: /location in source/i }), 'p. 42');
    await user.type(screen.getByRole('textbox', { name: /quote/i }), '  A quoted excerpt. ');
    await user.click(screen.getByRole('button', { name: 'Insert' }));
    expect(onsubmit).toHaveBeenCalledWith('p. 42', 'A quoted excerpt.');
  });

  it('skip-locator source with showQuote renders quote-only and focuses the textarea', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'web', skipLocator: true }),
      showQuote: true,
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.queryByRole('textbox', { name: /location in source/i })).toBeNull();
    const quoteInput = screen.getByRole('textbox', { name: /quote/i });
    expect(quoteInput).toHaveFocus();
    await user.keyboard('Verbatim.');
    await user.click(screen.getByRole('button', { name: 'Insert' }));
    expect(onsubmit).toHaveBeenCalledWith('', 'Verbatim.');
  });
});
