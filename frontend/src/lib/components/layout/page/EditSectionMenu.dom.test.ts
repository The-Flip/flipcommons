import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import EditSectionMenu from './EditSectionMenu.svelte';
import EditSectionMenuFixture from './EditSectionMenu.fixture.svelte';

describe('EditSectionMenu', () => {
  it('renders edit sections in a menu', async () => {
    const user = userEvent.setup();

    render(EditSectionMenuFixture);

    const trigger = screen.getByRole('button', { name: 'Edit' });
    await user.click(trigger);

    expect(screen.getByRole('menu')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Overview' })).toHaveAttribute(
      'href',
      '/models/medieval-madness/edit/overview',
    );
    expect(screen.getByRole('menuitem', { name: 'Technology' })).toHaveAttribute(
      'href',
      '/models/medieval-madness/edit/technology',
    );
    expect(screen.getByRole('menuitem', { name: 'Related Models' })).toHaveAttribute(
      'href',
      '/models/medieval-madness/edit/related-models',
    );
  });

  it('uses the current section label on the trigger and marks the current item as disabled', async () => {
    const user = userEvent.setup();

    render(EditSectionMenu, {
      props: {
        currentKey: 'overview',
        items: [
          { key: 'overview', label: 'Overview', href: '/models/medieval-madness/edit/overview' },
          {
            key: 'technology',
            label: 'Technology',
            href: '/models/medieval-madness/edit/technology',
          },
        ],
      },
    });

    const trigger = screen.getByRole('button', { name: 'Overview' });
    await user.click(trigger);

    expect(screen.getByRole('menuitem', { name: 'Overview' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(screen.getByRole('menuitem', { name: 'Technology' })).toHaveAttribute(
      'href',
      '/models/medieval-madness/edit/technology',
    );
  });

  it('disables the trigger when disabled is true', () => {
    render(EditSectionMenu, {
      props: {
        label: 'Overview',
        disabled: true,
        items: [
          { key: 'overview', label: 'Overview', href: '/models/medieval-madness/edit/overview' },
        ],
      },
    });

    expect(screen.getByRole('button', { name: 'Overview' })).toBeDisabled();
  });
});
