import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import SectionEditorModalErrorFixture from './SectionEditorModal.error-fixture.svelte';
import SectionEditorModalFixture from './SectionEditorModal.fixture.svelte';

function renderModal() {
  return render(SectionEditorModalFixture);
}

describe('SectionEditorModal', () => {
  afterEach(() => {
    document.body.style.overflow = '';
  });

  it('opens, locks scroll, and returns focus to the opener on Escape', async () => {
    const user = userEvent.setup();
    renderModal();

    const opener = screen.getByRole('button', { name: 'Open editor' });
    await user.click(opener);

    expect(screen.getByRole('dialog', { name: 'Edit Overview' })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');

    const closeButton = screen.getByRole('button', { name: 'Close' });
    await vi.waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Edit Overview' })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(opener).toHaveFocus();
    expect(screen.getByTestId('close-count')).toHaveTextContent('1');
  });

  it('closes from the backdrop and restores focus to the opener', async () => {
    const user = userEvent.setup();
    const { container } = renderModal();

    const opener = screen.getByRole('button', { name: 'Open editor' });
    await user.click(opener);

    const backdrop = container.querySelector('.backdrop-dismiss');
    expect(backdrop).toBeInTheDocument();

    await user.click(backdrop as Element);

    expect(screen.queryByRole('dialog', { name: 'Edit Overview' })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(opener).toHaveFocus();
    expect(screen.getByTestId('close-count')).toHaveTextContent('1');
  });

  it('runs save, closes, and restores focus to the opener', async () => {
    const user = userEvent.setup();
    renderModal();

    const opener = screen.getByRole('button', { name: 'Open editor' });
    await user.click(opener);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.queryByRole('dialog', { name: 'Edit Overview' })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(opener).toHaveFocus();
    expect(screen.getByTestId('save-count')).toHaveTextContent('1');
    expect(screen.getByTestId('close-count')).toHaveTextContent('0');
  });

  it('traps focus within the dialog when tabbing', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByRole('button', { name: 'Open editor' }));

    const closeButton = screen.getByRole('button', { name: 'Close' });
    const saveButton = screen.getByRole('button', { name: 'Save' });

    await vi.waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    // Shift-tab from first focusable wraps to last focusable
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(saveButton).toHaveFocus();

    // Tab from last focusable wraps to first focusable
    await user.keyboard('{Tab}');
    expect(closeButton).toHaveFocus();
  });

  it('displays the error message when error prop is set', () => {
    render(SectionEditorModalErrorFixture, {
      props: { error: 'Something went wrong' },
    });

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('does not display an error message when error prop is empty', () => {
    render(SectionEditorModalErrorFixture, {
      props: { error: '' },
    });

    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });

  it('Notes & Citations section starts collapsed', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByRole('button', { name: 'Open editor' }));

    const details = screen.getByText('Notes & Citations').closest('details');
    expect(details).toBeInTheDocument();
    expect(details).not.toHaveAttribute('open');
  });

  it('passes note and citation as null in onsave meta', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByRole('button', { name: 'Open editor' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('save-count')).toHaveTextContent('1');
    expect(screen.getByTestId('last-note')).toHaveTextContent('');
    expect(screen.getByTestId('last-citation')).toHaveTextContent('');
  });

  it('passes note value in onsave meta', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByRole('button', { name: 'Open editor' }));

    // Expand the Notes & Citations section
    await user.click(screen.getByText('Notes & Citations'));

    // Type a note
    const noteInput = screen.getByLabelText(/Edit note/);
    await user.type(noteInput, 'Corrected per IPDB');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-note')).toHaveTextContent('Corrected per IPDB');
  });

  it('resets note when modal reopens', async () => {
    const user = userEvent.setup();
    renderModal();

    // Open, type a note, close without saving
    await user.click(screen.getByRole('button', { name: 'Open editor' }));
    await user.click(screen.getByText('Notes & Citations'));
    const noteInput = screen.getByLabelText(/Edit note/);
    await user.type(noteInput, 'some note');
    await user.keyboard('{Escape}');

    // Reopen — note should be empty
    await user.click(screen.getByRole('button', { name: 'Open editor' }));
    await user.click(screen.getByText('Notes & Citations'));
    expect(screen.getByLabelText(/Edit note/)).toHaveValue('');
  });

  it('renders the section switcher in the modal header and switches sections', async () => {
    const user = userEvent.setup();
    render(SectionEditorModalFixture, {
      props: { showSwitcher: true },
    });

    await user.click(screen.getByRole('button', { name: 'Open editor' }));
    await user.click(screen.getByRole('button', { name: 'Overview' }));
    await user.click(screen.getByRole('menuitem', { name: 'Technology' }));

    expect(screen.getByTestId('last-switched')).toHaveTextContent('technology');
  });

  it('focuses Close on open even when the section switcher precedes it in DOM order', async () => {
    const user = userEvent.setup();
    render(SectionEditorModalFixture, {
      props: { showSwitcher: true },
    });

    await user.click(screen.getByRole('button', { name: 'Open editor' }));

    const closeButton = screen.getByRole('button', { name: 'Close' });
    await vi.waitFor(() => {
      expect(closeButton).toHaveFocus();
    });
  });

  it('disables the section switcher when switcherDisabled is true', async () => {
    const user = userEvent.setup();
    render(SectionEditorModalFixture, {
      props: { showSwitcher: true, switcherDisabled: true },
    });

    await user.click(screen.getByRole('button', { name: 'Open editor' }));

    expect(screen.getByRole('button', { name: 'Overview' })).toBeDisabled();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
