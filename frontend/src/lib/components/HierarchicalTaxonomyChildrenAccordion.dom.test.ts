import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import HierarchicalTaxonomyChildrenAccordionFixture from './HierarchicalTaxonomyChildrenAccordion.fixture.svelte';

describe('HierarchicalTaxonomyChildrenAccordion', () => {
  it('renders the accordion with the configured heading', () => {
    render(HierarchicalTaxonomyChildrenAccordionFixture);

    expect(screen.getByTestId('hierarchical-taxonomy-children-accordion')).toBeInTheDocument();
    expect(screen.getByText('Subtypes')).toBeInTheDocument();
  });

  it('renders nothing when children list is empty (accordion-no-empty-state rule)', () => {
    render(HierarchicalTaxonomyChildrenAccordionFixture, {
      props: { children: [] },
    });

    expect(screen.queryByTestId('hierarchical-taxonomy-children-accordion')).toBeNull();
    expect(screen.queryByText('Subtypes')).toBeNull();
  });

  it('expands to show child links with correct hrefs', async () => {
    const user = userEvent.setup();
    render(HierarchicalTaxonomyChildrenAccordionFixture);

    await user.click(screen.getByRole('button', { name: 'Subtypes' }));

    expect(screen.getByRole('link', { name: 'Slingshot' })).toHaveAttribute(
      'href',
      '/gameplay-features/slingshot',
    );
    expect(screen.getByRole('link', { name: 'Bumper' })).toHaveAttribute(
      'href',
      '/gameplay-features/bumper',
    );
  });

  it('honors per-entity heading and basePath (themes labels)', async () => {
    const user = userEvent.setup();
    render(HierarchicalTaxonomyChildrenAccordionFixture, {
      props: {
        basePath: '/themes',
        children: [{ name: 'Hockey', public_id: 'hockey' }],
        heading: 'Sub-themes (1)',
      },
    });

    expect(screen.getByText('Sub-themes (1)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sub-themes (1)' }));
    expect(screen.getByRole('link', { name: 'Hockey' })).toHaveAttribute('href', '/themes/hockey');
  });
});
