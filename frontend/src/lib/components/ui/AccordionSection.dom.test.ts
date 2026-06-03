import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import AccordionSectionFixture from './AccordionSection.fixture.svelte';

function renderAccordion() {
  return render(AccordionSectionFixture);
}

describe('AccordionSection', () => {
  it('toggles the section from its disclosure control', async () => {
    const user = userEvent.setup();
    renderAccordion();

    const toggle = screen.getByRole('button', { name: 'Overview' });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('region', { name: 'Overview' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'edit' })).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('region', { name: 'Overview' })).toHaveTextContent('Section content');
    expect(screen.getByRole('button', { name: 'edit' })).toBeInTheDocument();

    toggle.focus();
    await user.keyboard('{Enter}');

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('region', { name: 'Overview' })).not.toBeInTheDocument();
  });

  it('fires edit without collapsing the open section on keyboard activation', async () => {
    const user = userEvent.setup();
    renderAccordion();

    await user.click(screen.getByRole('button', { name: 'Overview' }));

    const editButton = screen.getByRole('button', { name: 'edit' });
    editButton.focus();
    await user.keyboard('{Enter}');

    expect(screen.getByTestId('edit-count')).toHaveTextContent('1');
    expect(screen.getByRole('button', { name: 'Overview' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByRole('region', { name: 'Overview' })).toBeInTheDocument();
  });

  it('keeps the edit control in the heading cluster while the toggle is labeled by the title', async () => {
    const user = userEvent.setup();
    const { container } = renderAccordion();

    await user.click(screen.getByRole('button', { name: 'Overview' }));

    const trigger = screen.getByRole('button', { name: 'Overview' });
    const heading = container.querySelector<HTMLElement>('.accordion-heading');
    const title = container.querySelector<HTMLElement>('.accordion-title');
    const editButton = container.querySelector<HTMLElement>('.accordion-heading .edit-link');

    expect(heading).toBeInTheDocument();
    expect(title).toBeInTheDocument();
    expect(editButton).toBeInTheDocument();
    expect(heading).toContainElement(editButton);
    expect(trigger).toHaveAttribute('aria-labelledby', title?.id);
  });
});
