import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import ButtonFixture from './Button.fixture.svelte';

describe('Button', () => {
  it('renders the destructive variant class when variant="destructive"', () => {
    render(ButtonFixture, { variant: 'destructive' });
    const btn = screen.getByRole('button', { name: 'Press me' });
    expect(btn).toHaveClass('btn-destructive');
  });

  it('applies the full-width class when fullWidth is true', () => {
    render(ButtonFixture, { variant: 'primary', fullWidth: true });
    expect(screen.getByRole('button', { name: 'Press me' })).toHaveClass('btn-full');
  });

  it('defaults to primary variant', () => {
    render(ButtonFixture);
    expect(screen.getByRole('button', { name: 'Press me' })).toHaveClass('btn-primary');
  });
});
