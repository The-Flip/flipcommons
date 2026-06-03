import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import DisplayOrderEditorFixture from './DisplayOrderEditor.fixture.svelte';

describe('DisplayOrderEditor', () => {
  it('reports clean state initially and dirty after editing', async () => {
    const user = userEvent.setup();
    render(DisplayOrderEditorFixture);

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.clear(screen.getByLabelText('Display order'));
    await user.type(screen.getByLabelText('Display order'), '5');

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('treats a null initial value as blank', async () => {
    render(DisplayOrderEditorFixture, { props: { initialData: null } });

    expect(screen.getByLabelText('Display order')).toHaveValue(null);
    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');
  });

  it('sends only the changed display_order in the save body', async () => {
    const user = userEvent.setup();
    render(DisplayOrderEditorFixture, { props: { initialData: 1 } });

    await user.clear(screen.getByLabelText('Display order'));
    await user.type(screen.getByLabelText('Display order'), '7');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({ fields: { display_order: 7 } }),
    );
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('skips the save call when clean', async () => {
    const user = userEvent.setup();
    render(DisplayOrderEditorFixture);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent('null');
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('surfaces field errors from the save result', async () => {
    const user = userEvent.setup();
    render(DisplayOrderEditorFixture, {
      props: {
        saveResult: {
          ok: false,
          error: 'boom',
          fieldErrors: { display_order: 'must be positive' },
        },
      },
    });

    await user.clear(screen.getByLabelText('Display order'));
    await user.type(screen.getByLabelText('Display order'), '7');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-error')).toHaveTextContent('Please fix the errors below.');
  });
});
