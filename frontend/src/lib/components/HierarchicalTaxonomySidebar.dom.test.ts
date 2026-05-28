import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import HierarchicalTaxonomySidebarFixture from './HierarchicalTaxonomySidebar.fixture.svelte';

describe('HierarchicalTaxonomySidebar', () => {
  it('renders parents under the configured heading with links', () => {
    render(HierarchicalTaxonomySidebarFixture);

    expect(screen.getByRole('heading', { name: 'Type of' })).toBeInTheDocument();
    const parentLink = screen.getByRole('link', { name: 'Physical Feature' });
    expect(parentLink).toHaveAttribute('href', '/gameplay-features/physical-feature');
  });

  it('renders children under the configured heading with links', () => {
    render(HierarchicalTaxonomySidebarFixture);

    expect(screen.getByRole('heading', { name: 'Subtypes' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Slingshot' })).toHaveAttribute(
      'href',
      '/gameplay-features/slingshot',
    );
    expect(screen.getByRole('link', { name: 'Bumper' })).toHaveAttribute(
      'href',
      '/gameplay-features/bumper',
    );
  });

  it('renders aliases comma-joined under the configured heading', () => {
    render(HierarchicalTaxonomySidebarFixture, {
      props: { aliases: ['Pop', 'Side Kicker'] },
    });

    expect(screen.getByRole('heading', { name: 'Also known as' })).toBeInTheDocument();
    expect(screen.getByText('Pop, Side Kicker')).toBeInTheDocument();
  });

  it('omits the parents section when there are no parents', () => {
    render(HierarchicalTaxonomySidebarFixture, {
      props: { parents: [] },
    });

    expect(screen.queryByRole('heading', { name: 'Type of' })).toBeNull();
  });

  it('omits the children section when there are none', () => {
    render(HierarchicalTaxonomySidebarFixture, {
      props: { children: [] },
    });

    expect(screen.queryByRole('heading', { name: 'Subtypes' })).toBeNull();
  });

  it('omits the aliases section when the list is empty', () => {
    render(HierarchicalTaxonomySidebarFixture, {
      props: { aliases: [] },
    });

    expect(screen.queryByRole('heading', { name: 'Also known as' })).toBeNull();
  });

  it('honors per-entity heading overrides (themes labels)', () => {
    render(HierarchicalTaxonomySidebarFixture, {
      props: {
        basePath: '/themes',
        parents: [{ name: 'Sports', public_id: 'sports' }],
        children: [{ name: 'Hockey', public_id: 'hockey' }],
        parentHeading: 'Parent themes',
        childHeading: 'Sub-themes',
      },
    });

    expect(screen.getByRole('heading', { name: 'Parent themes' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sub-themes' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sports' })).toHaveAttribute('href', '/themes/sports');
  });
});
