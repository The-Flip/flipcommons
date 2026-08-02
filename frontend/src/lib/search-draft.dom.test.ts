/**
 * Contract tests for `searchDraft`. The rule under test is which side wins when
 * the committed query and the draft disagree: a landing the draft itself caused
 * loses to the draft, anything arriving from outside wins.
 */
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import Harness from './search-draft.fixture.svelte';

const props = (committed: string, commit: (next: string) => void = vi.fn()) => ({
  committed,
  commit,
});

describe('searchDraft', () => {
  it('seeds the draft from the committed query', () => {
    render(Harness, { props: props('star') });
    expect(screen.getByRole('searchbox')).toHaveValue('star');
  });

  it('commits once per typing pause, trimmed', async () => {
    const user = userEvent.setup();
    const commit = vi.fn();
    render(Harness, { props: props('', commit) });

    await user.type(screen.getByRole('searchbox'), '  star ');

    await waitFor(() => expect(commit).toHaveBeenCalledTimes(1));
    expect(commit).toHaveBeenCalledWith('star');
  });

  it('keeps a draft typed ahead of the landing it caused', async () => {
    const user = userEvent.setup();
    const commit = vi.fn();
    const { rerender } = render(Harness, { props: props('', commit) });
    const box = screen.getByRole('searchbox');

    await user.type(box, 'god');
    await waitFor(() => expect(commit).toHaveBeenCalledWith('god'));

    // The user types on while that commit's navigation is in flight, then it
    // lands and the load reseeds the committed query.
    await user.type(box, 'zi');
    await rerender(props('god', commit));

    expect(box).toHaveValue('godzi');
  });

  it('replaces the draft when a query arrives from outside', async () => {
    const { rerender } = render(Harness, { props: props('star') });
    expect(screen.getByRole('searchbox')).toHaveValue('star');

    await rerender(props('addams'));

    expect(screen.getByRole('searchbox')).toHaveValue('addams');
  });

  it('abandons a scheduled commit when an outside query arrives', async () => {
    const user = userEvent.setup();
    const commit = vi.fn();
    const { rerender } = render(Harness, { props: props('star', commit) });
    const box = screen.getByRole('searchbox');

    await user.type(box, 'fi');
    await rerender(props('addams', commit));
    expect(box).toHaveValue('addams');

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(box).toHaveValue('addams');
    expect(commit).not.toHaveBeenCalled();
  });

  // Some pages commit a query without going through the draft — a filter control
  // that navigates while preserving `q`. Recording it keeps that landing on the
  // "ours" side of the rule, so it doesn't wipe what the user is typing.
  it('treats a query recorded via markCommitted as one of its own', async () => {
    const user = userEvent.setup();
    const commit = vi.fn();
    const { rerender } = render(Harness, { props: props('star', commit) });
    const box = screen.getByRole('searchbox');

    await user.type(box, 'fi');
    await user.click(screen.getByRole('button', { name: /mark committed/i }));

    await rerender(props('outside', commit));

    expect(box).toHaveValue('starfi');
  });
});
