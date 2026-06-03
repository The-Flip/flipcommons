import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ModalFooterFixture from './Modal.footer.fixture.svelte';
import ModalFixture from './Modal.fixture.svelte';
import ModalSwitchingFixture from './Modal.switching.fixture.svelte';

function renderModal() {
  return render(ModalFixture);
}

describe('Modal', () => {
  afterEach(() => {
    document.body.style.overflow = '';
  });

  it('opens, locks scroll, and returns focus to the opener on Escape', async () => {
    const user = userEvent.setup();
    renderModal();

    const opener = screen.getByRole('button', { name: 'Open modal' });
    await user.click(opener);

    expect(screen.getByRole('dialog', { name: 'Edit Media' })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');

    const closeButton = screen.getByRole('button', { name: 'Close' });
    await vi.waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Edit Media' })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(opener).toHaveFocus();
    expect(screen.getByTestId('close-count')).toHaveTextContent('1');
  });

  it('closes from the backdrop and restores focus to the opener', async () => {
    const user = userEvent.setup();
    const { container } = renderModal();

    const opener = screen.getByRole('button', { name: 'Open modal' });
    await user.click(opener);

    const backdrop = container.querySelector('.backdrop-dismiss');
    expect(backdrop).toBeInTheDocument();

    await user.click(backdrop as Element);

    expect(screen.queryByRole('dialog', { name: 'Edit Media' })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(opener).toHaveFocus();
    expect(screen.getByTestId('close-count')).toHaveTextContent('1');
  });

  it('does not render a footer when none is provided', async () => {
    const user = userEvent.setup();
    const { container } = renderModal();

    await user.click(screen.getByRole('button', { name: 'Open modal' }));

    expect(container.querySelector('.modal-footer')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Upload' })).not.toBeInTheDocument();
  });

  it('restores body scroll when switching between concurrent modals', async () => {
    const user = userEvent.setup();
    render(ModalSwitchingFixture);

    const openA = screen.getByRole('button', { name: 'Open A' });
    const openB = screen.getByRole('button', { name: 'Open B' });

    // Open later-rendered modal B first, then switch to earlier-rendered A.
    // With per-instance snapshots + creation-order effects, A captures
    // prev='hidden' (from B still open) before B cleans up — leaking the
    // lock when A later closes.
    await user.click(openB);
    expect(screen.getByRole('dialog', { name: 'Modal B' })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');

    await user.click(openA);
    await vi.waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Modal A' })).toBeInTheDocument();
    });
    expect(document.body.style.overflow).toBe('hidden');

    // Close A — no modals open, body should be unlocked.
    await user.keyboard('{Escape}');
    await vi.waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(document.body.style.overflow).toBe('');
  });

  it('renders a custom footer and traps focus within the dialog when tabbing', async () => {
    const user = userEvent.setup();
    const { container } = render(ModalFooterFixture);

    await user.click(screen.getByRole('button', { name: 'Open modal' }));

    const closeButton = screen.getByRole('button', { name: 'Close' });
    const uploadButton = screen.getByRole('button', { name: 'Upload' });

    expect(container.querySelector('.modal-footer')).toBeInTheDocument();

    await vi.waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(uploadButton).toHaveFocus();

    await user.keyboard('{Tab}');
    expect(closeButton).toHaveFocus();
  });
});
