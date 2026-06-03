import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import Avatar, { initialsFor } from './Avatar.svelte';

describe('initialsFor', () => {
  it('uses first + last initial when both present', () => {
    expect(initialsFor({ firstName: 'Alice', lastName: 'Anderson', username: 'alice' })).toBe('AA');
  });

  it('falls back to first initial when last name is empty', () => {
    expect(initialsFor({ firstName: 'Alice', lastName: '', username: 'alice' })).toBe('A');
  });

  it('falls back to first two username chars when no names', () => {
    expect(initialsFor({ firstName: '', lastName: '', username: 'bobby' })).toBe('BO');
  });

  it('handles whitespace-only names as missing', () => {
    expect(initialsFor({ firstName: '  ', lastName: '  ', username: 'carol' })).toBe('CA');
  });

  it('uppercases lowercase input', () => {
    expect(initialsFor({ firstName: 'dan', lastName: 'doe', username: 'dan' })).toBe('DD');
  });

  it('treats null/undefined names as missing', () => {
    expect(initialsFor({ firstName: null, lastName: undefined, username: 'eve' })).toBe('EV');
  });
});

describe('Avatar', () => {
  it('renders the computed initials', () => {
    render(Avatar, { firstName: 'Alice', lastName: 'Anderson', username: 'alice' });
    expect(screen.getByTestId('avatar')).toHaveTextContent('AA');
  });
});
