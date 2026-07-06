/** Tests for the shared citation row body: labeled + hinted fields (never
 *  placeholder-only), the add-locator reveal and the consumer action slots.
 *  The panel-level behaviors over multiple rows live in
 *  InlineCitationsPanel.dom.test.ts. */
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import CitationInstanceFields from './CitationInstanceFields.svelte';
import CitationInstanceFieldsFixture from './CitationInstanceFields.fixture.svelte';

describe('CitationInstanceFields', () => {
  it('labels the quote and (revealed) locator with persistent hints, not placeholders', async () => {
    const user = userEvent.setup();
    render(CitationInstanceFieldsFixture);

    expect(screen.getByRole('textbox', { name: /quote/i })).toBeInTheDocument();
    expect(screen.getByText('Exact text quoted from the source')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Add a locator' }));
    const locatorInput = screen.getByRole('textbox', { name: /location in source/i });
    expect(locatorInput).toHaveFocus();
    expect(screen.getByText('e.g. p. 42, Chapter 3, a timestamp')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add a locator' })).toBeNull();
  });

  it('labels the locator per citation type (a video asks for a start time)', () => {
    render(CitationInstanceFields, {
      citation: {
        sourceName: 'YouTube #dQw4w9WgXcQ',
        sourceType: 'video',
        locator: '1:35',
        quote: '',
      },
    });
    expect(screen.getByRole('textbox', { name: /start time/i })).toHaveValue('1:35');
    expect(screen.queryByRole('button', { name: 'Add a locator' })).toBeNull();
  });

  it('keeps an opened locator input visible after its text is cleared', async () => {
    const user = userEvent.setup();
    render(CitationInstanceFieldsFixture);

    await user.click(screen.getByRole('button', { name: 'Add a locator' }));
    const locatorInput = screen.getByRole('textbox', { name: /location in source/i });
    await user.type(locatorInput, 'p. 42');
    await user.clear(locatorInput);

    expect(screen.getByRole('textbox', { name: /location in source/i })).toBeInTheDocument();
  });

  it('edits write through to the host citation', async () => {
    const user = userEvent.setup();
    render(CitationInstanceFieldsFixture);

    await user.click(screen.getByRole('button', { name: 'Add a locator' }));
    await user.type(screen.getByRole('textbox', { name: /location in source/i }), 'p. 42');
    await user.type(screen.getByRole('textbox', { name: /quote/i }), 'Verbatim.');

    expect(screen.getByTestId('citation-json')).toHaveTextContent(
      JSON.stringify({
        sourceName: 'The Encyclopedia of Pinball',
        sourceType: 'book',
        locator: 'p. 42',
        quote: 'Verbatim.',
      }),
    );
  });

  it('renders the header Remove button only when onremove is provided, and calls it', async () => {
    const user = userEvent.setup();
    render(CitationInstanceFieldsFixture, { withRemove: true });

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(screen.getByTestId('removed')).toHaveTextContent('true');
  });

  it('omits the Remove button without onremove and still renders consumer actions', () => {
    render(CitationInstanceFieldsFixture);
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Change citation' })).toBeInTheDocument();
  });
});
