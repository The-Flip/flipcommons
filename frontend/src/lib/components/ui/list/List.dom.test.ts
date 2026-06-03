import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import ListFixture from './List.fixture.svelte';

describe('List + ListItem', () => {
  it('renders each row from the caller-owned loop', () => {
    render(ListFixture);
    expect(screen.getByText('First row')).toBeInTheDocument();
    expect(screen.getByText('Second row')).toBeInTheDocument();
  });

  it('omits the actions wrapper entirely when no snippet is provided', () => {
    const { container } = render(ListFixture);
    expect(screen.queryByTestId('row-action')).not.toBeInTheDocument();
    expect(container.querySelector('.actions')).toBeNull();
  });

  it('renders the actions wrapper when a snippet is supplied', () => {
    const { container } = render(ListFixture, { withActions: true });
    expect(screen.getByTestId('row-action')).toBeInTheDocument();
    expect(container.querySelector('.actions')).not.toBeNull();
  });

  it('wraps content in an anchor when href is supplied', () => {
    render(ListFixture, { href: '/kiosk/edit/42' });
    const link = screen.getByText('First row').closest('a');
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute('href', '/kiosk/edit/42');
  });

  it('renders content as a div when href is omitted', () => {
    render(ListFixture);
    expect(screen.getByText('First row').closest('a')).toBeNull();
  });
});
