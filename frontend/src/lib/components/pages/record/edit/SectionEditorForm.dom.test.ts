import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import SectionEditorFormFixture from './SectionEditorForm.fixture.svelte';

describe('SectionEditorForm', () => {
  it('renders save and cancel buttons', () => {
    render(SectionEditorFormFixture);

    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('calls onsave with note and citation when save is clicked', async () => {
    const user = userEvent.setup();
    render(SectionEditorFormFixture);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('save-count')).toHaveTextContent('1');
    expect(screen.getByTestId('last-note')).toHaveTextContent('');
    expect(screen.getByTestId('last-citation')).toHaveTextContent('');
  });

  it('calls oncancel when cancel is clicked', async () => {
    const user = userEvent.setup();
    render(SectionEditorFormFixture);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.getByTestId('cancel-count')).toHaveTextContent('1');
  });

  it('passes note value in onsave meta', async () => {
    const user = userEvent.setup();
    render(SectionEditorFormFixture);

    await user.click(screen.getByText('Notes & Citations'));

    const noteInput = screen.getByLabelText(/Edit note/);
    await user.type(noteInput, 'Corrected per IPDB');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-note')).toHaveTextContent('Corrected per IPDB');
  });

  it('Notes & Citations section starts collapsed', () => {
    render(SectionEditorFormFixture);

    const details = screen.getByText('Notes & Citations').closest('details');
    expect(details).toBeInTheDocument();
    expect(details).not.toHaveAttribute('open');
  });

  it('displays error message when error prop is set', () => {
    render(SectionEditorFormFixture, {
      props: { error: 'Something went wrong' },
    });

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('does not display error message when error prop is empty', () => {
    render(SectionEditorFormFixture, {
      props: { error: '' },
    });

    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });

  it('hides citation field when showCitation is false', () => {
    render(SectionEditorFormFixture, {
      props: { showCitation: false },
    });

    // Summary text should say "Notes" not "Notes & Citations"
    expect(screen.getByText('Notes')).toBeInTheDocument();
    expect(screen.queryByText('Notes & Citations')).not.toBeInTheDocument();
  });

  it('renders children content', () => {
    render(SectionEditorFormFixture);

    expect(screen.getByLabelText('Description')).toBeInTheDocument();
  });
});
