import { fireEvent, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import ActionMenuFixture from './ActionMenu.fixture.svelte';
import ActionMenuListboxFixture from './ActionMenu.listbox.fixture.svelte';
import ActionMenuPortalFixture from './ActionMenu.portal.fixture.svelte';
import ActionMenuTriggerFixture from './ActionMenu.trigger.fixture.svelte';

describe('ActionMenu', () => {
  function renderMenu() {
    return render(ActionMenuFixture);
  }

  it('opens on click and renders menu semantics without forcing focus into the menu', async () => {
    const user = userEvent.setup();

    renderMenu();

    const trigger = screen.getByRole('button', { name: 'Tools' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    await user.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const menu = screen.getByRole('menu');
    expect(menu).toBeInTheDocument();
    expect(menu).toHaveAttribute('data-placement', 'bottom-end');
    expect(screen.getByRole('menuitem', { name: 'Sources' })).toHaveAttribute(
      'href',
      '/models/medieval-madness/sources',
    );
    expect(trigger).toHaveFocus();
  });

  it('portals the menu out of clipping ancestors', async () => {
    const user = userEvent.setup();

    render(ActionMenuPortalFixture);

    await user.click(screen.getByRole('button', { name: 'Tools' }));

    const menu = screen.getByRole('menu');
    const wrapper = screen.getByTestId('clip-wrapper');
    expect(wrapper).not.toContainElement(menu);
  });

  it('opens from the keyboard and focuses the first item', async () => {
    const user = userEvent.setup();

    renderMenu();

    const trigger = screen.getByRole('button', { name: 'Tools' });
    trigger.focus();

    await user.keyboard('{ArrowDown}');

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menu')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Sources' })).toHaveFocus();
    expect(screen.getByRole('menuitem', { name: 'History' })).toHaveAttribute('tabindex', '-1');
  });

  it('opens from ArrowUp on the trigger and focuses the last item', async () => {
    const user = userEvent.setup();

    renderMenu();

    const trigger = screen.getByRole('button', { name: 'Tools' });
    trigger.focus();

    await user.keyboard('{ArrowUp}');

    expect(screen.getByRole('menuitem', { name: 'Export' })).toHaveFocus();
  });

  it('supports arrow-key roving focus and Home/End inside the menu', async () => {
    const user = userEvent.setup();

    renderMenu();

    const trigger = screen.getByRole('button', { name: 'Tools' });
    trigger.focus();
    await user.keyboard('{ArrowDown}');

    const sources = screen.getByRole('menuitem', { name: 'Sources' });
    const history = screen.getByRole('menuitem', { name: 'History' });
    const exportItem = screen.getByRole('menuitem', { name: 'Export' });

    expect(sources).toHaveAttribute('tabindex', '0');
    expect(history).toHaveAttribute('tabindex', '-1');

    await user.keyboard('{ArrowDown}');
    expect(history).toHaveFocus();
    expect(history).toHaveAttribute('tabindex', '0');
    expect(sources).toHaveAttribute('tabindex', '-1');

    await user.keyboard('{End}');
    expect(exportItem).toHaveFocus();

    await user.keyboard('{Home}');
    expect(sources).toHaveFocus();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const user = userEvent.setup();

    renderMenu();

    const trigger = screen.getByRole('button', { name: 'Tools' });
    trigger.focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menu')).toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
  });

  it('closes on outside pointer down', async () => {
    const user = userEvent.setup();

    renderMenu();

    const trigger = screen.getByRole('button', { name: 'Tools' });

    await user.click(trigger);
    expect(screen.getByRole('menu')).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  describe('custom trigger snippet', () => {
    it('renders the snippet inside the button and keeps keyboard/ARIA wiring', async () => {
      const user = userEvent.setup();
      render(ActionMenuTriggerFixture);

      const trigger = screen.getByRole('button', { name: 'Account' });
      expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');

      const customContent = screen.getByTestId('custom-trigger');
      expect(trigger).toContainElement(customContent);
      expect(customContent).toHaveTextContent('AB');

      trigger.focus();
      await user.keyboard('{ArrowDown}');

      expect(trigger).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByRole('menuitem', { name: 'Profile' })).toHaveFocus();
    });
  });

  describe('pill variant + listbox role', () => {
    it('renders listbox semantics by default for variant="pill"', async () => {
      const user = userEvent.setup();
      render(ActionMenuListboxFixture);

      const trigger = screen.getByRole('button', { name: 'Image category: playfield' });
      expect(trigger).toHaveAttribute('aria-haspopup', 'listbox');

      await user.click(trigger);

      const listbox = screen.getByRole('listbox');
      expect(listbox).toBeInTheDocument();
      expect(listbox).toHaveAttribute('data-placement', 'top-start');

      const options = screen.getAllByRole('option');
      expect(options.map((o) => o.textContent?.trim())).toEqual([
        'playfield',
        'backglass',
        'cabinet',
      ]);

      const current = screen.getByRole('option', { name: 'playfield' });
      expect(current).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('option', { name: 'backglass' })).toHaveAttribute(
        'aria-selected',
        'false',
      );
    });

    it('arrow keys move focus across options and Escape closes', async () => {
      const user = userEvent.setup();
      render(ActionMenuListboxFixture);

      const trigger = screen.getByRole('button', { name: 'Image category: playfield' });
      trigger.focus();
      await user.keyboard('{ArrowDown}');

      expect(screen.getByRole('option', { name: 'playfield' })).toHaveFocus();
      await user.keyboard('{ArrowDown}');
      expect(screen.getByRole('option', { name: 'backglass' })).toHaveFocus();
      await user.keyboard('{End}');
      expect(screen.getByRole('option', { name: 'cabinet' })).toHaveFocus();

      await user.keyboard('{Escape}');
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });

    it('clicking an option closes the listbox and restores focus to the trigger', async () => {
      const user = userEvent.setup();
      const onselect = vi.fn();
      render(ActionMenuListboxFixture, { onselect });

      const trigger = screen.getByRole('button', { name: 'Image category: playfield' });
      await user.click(trigger);
      await user.click(screen.getByRole('option', { name: 'backglass' }));

      expect(onselect).toHaveBeenCalledWith('backglass');
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      // Trigger label re-renders with the new selection.
      expect(screen.getByRole('button', { name: 'Image category: backglass' })).toHaveFocus();
    });
  });
});
