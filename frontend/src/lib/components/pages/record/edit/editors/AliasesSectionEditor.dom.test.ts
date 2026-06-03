import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import AliasesSectionEditorFixture from './AliasesSectionEditor.fixture.svelte';

describe('AliasesSectionEditor', () => {
  it('reports clean state initially', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture);

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');
  });

  it('reports dirty after adding an alias', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture);

    await user.type(screen.getByLabelText('Aliases'), 'Side Kicker{Enter}');

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');
  });

  it('reports dirty after removing an alias', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture);

    await user.click(screen.getByRole('button', { name: 'Remove Slingshot' }));

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');
  });

  it('treats reordering as clean (set semantics)', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture, {
      props: { initialData: { aliases: ['A', 'B'] } },
    });

    // Remove A then re-add — same set, different order
    await user.click(screen.getByRole('button', { name: 'Remove A' }));
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.type(screen.getByLabelText('Aliases'), 'A{Enter}');
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');
  });

  it('sends the full aliases list in the save body when dirty', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture);

    await user.type(screen.getByLabelText('Aliases'), 'Side Kicker{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({ aliases: ['Slingshot', 'Side Kicker'] }),
    );
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('skips the save call when clean', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent('null');
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('forwards SaveMeta (note, citation) to the save function', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture);

    await user.type(screen.getByLabelText('Aliases'), 'Bumper{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save with note' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({ aliases: ['Slingshot', 'Bumper'], note: 'rationale' }),
    );
  });

  it('surfaces field errors from the save result', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture, {
      props: {
        saveResult: {
          ok: false,
          error: 'boom',
          fieldErrors: { aliases: 'duplicate value' },
        },
      },
    });

    await user.type(screen.getByLabelText('Aliases'), 'Bumper{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-error')).toHaveTextContent('Please fix the errors below.');
  });

  it('surfaces a non-field error when no fieldErrors are returned', async () => {
    const user = userEvent.setup();
    render(AliasesSectionEditorFixture, {
      props: {
        saveResult: {
          ok: false,
          error: 'server exploded',
          fieldErrors: {},
        },
      },
    });

    await user.type(screen.getByLabelText('Aliases'), 'Bumper{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-error')).toHaveTextContent('server exploded');
  });
});
