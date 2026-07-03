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
    ...overrides,
  };
}

describe('CitationLocatorStage', () => {
  it('shows the freeform placeholder for a book', () => {
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'book' }),
      onsubmit: noop,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.getByLabelText('Citation locator')).toHaveAttribute(
      'placeholder',
      'p. 42, Chapter 3, timestamp...',
    );
  });

  it('shows the timestamp placeholder for a video', () => {
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'video' }),
      onsubmit: noop,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.getByLabelText('Citation locator')).toHaveAttribute(
      'placeholder',
      'e.g. 1:02:03',
    );
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
    const input = screen.getByLabelText('Citation locator');
    expect(input).toHaveValue('1:35');
    expect(onsubmit).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Insert' }));
    expect(onsubmit).toHaveBeenCalledWith('1:35');
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
    await user.type(screen.getByLabelText('Citation locator'), '1h2m3s{Enter}');
    expect(onsubmit).toHaveBeenCalledWith('1:02:03');
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
    await user.type(screen.getByLabelText('Citation locator'), 'p. 42{Enter}');
    expect(onsubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/start time/);
    // Typing again clears the error.
    await user.type(screen.getByLabelText('Citation locator'), '5');
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
    await user.type(screen.getByLabelText('Citation locator'), 'p. 42{Enter}');
    expect(onsubmit).toHaveBeenCalledWith('p. 42');
  });

  it('skip always submits an empty locator, even for video', async () => {
    const user = userEvent.setup();
    const onsubmit = vi.fn();
    render(CitationLocatorStage, {
      draft: makeDraft({ sourceType: 'video', locatorHint: '1:35' }),
      onsubmit,
      oncancel: noop,
      onback: noop,
    });
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    expect(onsubmit).toHaveBeenCalledWith('');
  });
});
