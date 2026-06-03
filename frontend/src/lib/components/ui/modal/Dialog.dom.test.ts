import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DialogFixture from './Dialog.fixture.svelte';

describe('Dialog', () => {
  afterEach(() => {
    document.body.style.overflow = '';
  });

  it('opens, exposes role+name, locks scroll, restores focus on Escape', async () => {
    const user = userEvent.setup();
    render(DialogFixture);

    const opener = screen.getByRole('button', { name: 'Open dialog' });
    await user.click(opener);

    expect(screen.getByRole('dialog', { name: 'Test Dialog' })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Test Dialog' })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(opener).toHaveFocus();
    expect(screen.getByTestId('close-count')).toHaveTextContent('1');
  });

  it('supports ariaLabelledBy as the accessible-name source', async () => {
    const user = userEvent.setup();
    render(DialogFixture, { props: { useAriaLabelledBy: true } });

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));

    expect(screen.getByRole('dialog', { name: 'Dialog Title' })).toBeInTheDocument();
  });

  it('closes on backdrop click', async () => {
    const user = userEvent.setup();
    const { container } = render(DialogFixture);

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));

    const backdrop = container.querySelector('.backdrop-dismiss');
    expect(backdrop).toBeInTheDocument();
    await user.click(backdrop as Element);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('close-count')).toHaveTextContent('1');
  });

  it('focuses the first focusable descendant by default', async () => {
    const user = userEvent.setup();
    render(DialogFixture);

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));

    const first = screen.getByRole('button', { name: 'First' });
    await vi.waitFor(() => {
      expect(first).toHaveFocus();
    });
  });

  it('focuses initialFocus when provided and connected', async () => {
    const user = userEvent.setup();
    render(DialogFixture, { props: { useInitialFocus: true } });

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));

    const second = screen.getByRole('button', { name: 'Second' });
    await vi.waitFor(() => {
      expect(second).toHaveFocus();
    });
  });

  it('falls back to first focusable when initialFocus is a stale (disconnected) ref', async () => {
    const user = userEvent.setup();
    render(DialogFixture, { props: { useStaleInitialFocus: true } });

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));

    const first = screen.getByRole('button', { name: 'First' });
    await vi.waitFor(() => {
      expect(first).toHaveFocus();
    });
  });

  it('traps focus when tabbing forward and backward', async () => {
    const user = userEvent.setup();
    render(DialogFixture);

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));

    const first = screen.getByRole('button', { name: 'First' });
    const second = screen.getByRole('button', { name: 'Second' });

    await vi.waitFor(() => {
      expect(first).toHaveFocus();
    });

    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(second).toHaveFocus();

    await user.keyboard('{Tab}');
    expect(first).toHaveFocus();
  });
});
