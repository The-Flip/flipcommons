import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import InlineCitationsPanel from './InlineCitationsPanel.svelte';
import InlineCitationsPanelFixture from './InlineCitationsPanel.fixture.svelte';
import type { PendingInlineCitation } from '$lib/pending-citations';

function pending(slug: string, overrides: Partial<PendingInlineCitation> = {}) {
  return {
    slug,
    sourceId: 1,
    sourceName: 'The Encyclopedia of Pinball',
    sourceType: 'book',
    locator: '',
    quote: '',
    ...overrides,
  };
}

/** The row for one pending cite, located by its source-name group label. */
function row(sourceName: string) {
  return within(screen.getByRole('group', { name: sourceName }));
}

describe('InlineCitationsPanel', () => {
  it('renders nothing when no pending marker survives in the text', () => {
    render(InlineCitationsPanel, {
      pending: [pending('rrrrrrrr')],
      text: 'The marker was deleted.',
    });
    expect(screen.queryByText('Inline citations')).toBeNull();
  });

  it('shows one labeled row per surviving marker, with a labeled + hinted quote field', () => {
    render(InlineCitationsPanel, {
      pending: [pending('aaaaaaaa'), pending('rrrrrrrr')],
      text: 'Kept.[[cite:aaaaaaaa]]',
    });
    expect(screen.getByText('Inline citations')).toBeInTheDocument();

    const kept = row('The Encyclopedia of Pinball');
    // The quote field carries a real label and persistent helper text — the
    // same FieldGroup pattern as the picker's locator stage, not placeholders.
    expect(kept.getByRole('textbox', { name: /quote/i })).toBeInTheDocument();
    expect(kept.getByText('Exact text quoted from the source')).toBeInTheDocument();
  });

  it('keeps the locator unprompted: no input until "Add a locator" is clicked', async () => {
    const user = userEvent.setup();
    render(InlineCitationsPanel, {
      pending: [pending('aaaaaaaa')],
      text: 'Kept.[[cite:aaaaaaaa]]',
    });

    // Unprompted: an empty locator renders no input, just the affordance.
    expect(screen.queryByRole('textbox', { name: /location in source/i })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Add a locator' }));

    // Reachable: the labeled input appears focused with its help text, and
    // the affordance collapses.
    const locatorInput = screen.getByRole('textbox', { name: /location in source/i });
    expect(locatorInput).toHaveFocus();
    expect(screen.getByText('e.g. p. 42, Chapter 3, a timestamp')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add a locator' })).toBeNull();
  });

  it('labels the locator per citation type (a video asks for a start time)', () => {
    render(InlineCitationsPanel, {
      pending: [
        pending('aaaaaaaa', {
          sourceName: 'YouTube #dQw4w9WgXcQ',
          sourceType: 'video',
          locator: '1:35',
        }),
      ],
      text: 'Kept.[[cite:aaaaaaaa]]',
    });
    expect(screen.getByRole('textbox', { name: /start time/i })).toHaveValue('1:35');
    expect(
      screen.getByText('Where to begin watching — e.g. 1:02:03, 95, or 1h2m3s'),
    ).toBeInTheDocument();
  });

  it('shows the locator input when the cite already carries one (entered at the picker)', () => {
    render(InlineCitationsPanel, {
      pending: [pending('aaaaaaaa', { locator: 'p. 42' })],
      text: 'Kept.[[cite:aaaaaaaa]]',
    });
    expect(screen.getByRole('textbox', { name: /location in source/i })).toHaveValue('p. 42');
    expect(screen.queryByRole('button', { name: 'Add a locator' })).toBeNull();
  });

  it('keeps an opened locator input visible after its text is cleared', async () => {
    // Clearing the value must not yank the field out from under the
    // contributor — same rule as EditCitationField.
    const user = userEvent.setup();
    render(InlineCitationsPanelFixture);

    await user.click(screen.getByRole('button', { name: 'Add a locator' }));
    const locatorInput = screen.getByRole('textbox', { name: /location in source/i });
    await user.type(locatorInput, 'p. 42');
    await user.clear(locatorInput);

    expect(screen.getByRole('textbox', { name: /location in source/i })).toBeInTheDocument();
  });

  it('edits write through to the pending entries (revisitable until save)', async () => {
    const user = userEvent.setup();
    render(InlineCitationsPanelFixture);

    await user.click(screen.getByRole('button', { name: 'Add a locator' }));
    await user.type(screen.getByRole('textbox', { name: /location in source/i }), 'p. 42');
    await user.type(screen.getByRole('textbox', { name: /quote/i }), 'Verbatim.');

    expect(screen.getByTestId('pending-json')).toHaveTextContent(
      JSON.stringify([
        {
          slug: 'aaaaaaaa',
          sourceId: 1,
          sourceName: 'The Encyclopedia of Pinball',
          sourceType: 'book',
          locator: 'p. 42',
          quote: 'Verbatim.',
        },
      ]),
    );
  });
});
