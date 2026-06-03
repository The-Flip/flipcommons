import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import FilterDrawerFixture from './FilterDrawer.fixture.svelte';

function renderDrawer() {
  return render(FilterDrawerFixture);
}

describe('FilterDrawer', () => {
  beforeEach(() => {
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 0;
    });
  });

  afterEach(() => {
    document.body.style.overflow = '';
    vi.restoreAllMocks();
  });

  it('opens and closes from the toggle button while locking body scroll', async () => {
    const user = userEvent.setup();
    renderDrawer();

    const toggle = screen.getByRole('button', { name: /^filters$/i });
    const dialog = screen.getByRole('dialog', { name: /filter manufacturers/i });

    await user.click(toggle);

    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(document.body.style.overflow).toBe('hidden');

    const closeButton = within(dialog).getByRole('button', { name: /close filters/i });
    await vi.waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    await user.click(closeButton);

    expect(dialog).toHaveAttribute('aria-modal', 'false');
    expect(document.body.style.overflow).toBe('');
    expect(toggle).toHaveFocus();
  });

  it('closes on Escape', async () => {
    const user = userEvent.setup();
    renderDrawer();

    const toggle = screen.getByRole('button', { name: /^filters$/i });
    const dialog = screen.getByRole('dialog', { name: /filter manufacturers/i });

    await user.click(toggle);
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    await user.keyboard('{Escape}');

    expect(dialog).toHaveAttribute('aria-modal', 'false');
    expect(document.body.style.overflow).toBe('');
    expect(toggle).toHaveFocus();
  });

  it('closes when the backdrop is clicked', async () => {
    const user = userEvent.setup();
    const { container } = renderDrawer();

    const toggle = screen.getByRole('button', { name: /^filters$/i });
    const dialog = screen.getByRole('dialog', { name: /filter manufacturers/i });

    await user.click(toggle);
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    const backdrop = container.querySelector('.backdrop');
    expect(backdrop).toBeInTheDocument();

    await user.click(backdrop as Element);

    expect(dialog).toHaveAttribute('aria-modal', 'false');
    expect(document.body.style.overflow).toBe('');
    expect(toggle).toHaveFocus();
  });
});
