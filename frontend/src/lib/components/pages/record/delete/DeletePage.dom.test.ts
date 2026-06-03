import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DeletePage from './DeletePage.svelte';
import type { BlockedState } from './delete-page';
import type { DeleteOutcome, BlockingReferrer } from '$lib/delete-flow';
import { toast } from '$lib/toast/toast.svelte';

const { goto, resolve, submitUndoDelete } = vi.hoisted(() => ({
  goto: vi.fn(),
  // `resolve` from $app/paths is the underlying call inside resolveHref;
  // stub to identity so tests can assert against the raw href strings.
  resolve: vi.fn((url: string) => url),
  submitUndoDelete: vi.fn(),
}));

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/paths', () => ({ resolve }));
vi.mock('$lib/undo-delete', () => ({ submitUndoDelete }));

type Response = { changeset_id: number };
type Submit = (
  public_id: string,
  opts: { note: string; citation: import('$lib/edit-citation').EditCitationSelection | null },
) => Promise<DeleteOutcome<Response>>;

function makeImpact() {
  return { items: ['1 thing'], note: 'Undo from the toast.' };
}

function renderUnblocked(submit: Submit) {
  return render(DeletePage<Response>, {
    entityLabel: 'Title',
    entityName: 'Attack from Mars',
    public_id: 'attack-from-mars',
    submit,
    cancelHref: '/titles/attack-from-mars',
    redirectAfterDelete: '/titles',
    editHistoryHref: '/titles/attack-from-mars/edit-history',
    blocked: null,
    impact: makeImpact(),
  });
}

describe('DeletePage', () => {
  beforeEach(() => {
    goto.mockReset();
    goto.mockResolvedValue(undefined);
    submitUndoDelete.mockReset();
    toast._resetForTest();
  });

  afterEach(() => {
    toast._resetForTest();
  });

  it('navigates to cancelHref via resolveHref when Cancel is clicked', async () => {
    const user = userEvent.setup();
    renderUnblocked(vi.fn());

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(resolve).toHaveBeenCalledWith('/titles/attack-from-mars');
    expect(goto).toHaveBeenCalledWith('/titles/attack-from-mars');
  });

  it('on success: shows undo toast and navigates to redirectAfterDelete', async () => {
    const user = userEvent.setup();
    const submit = vi.fn<Submit>().mockResolvedValue({ kind: 'ok', data: { changeset_id: 42 } });
    renderUnblocked(submit);

    await user.click(screen.getByRole('button', { name: 'Delete Title' }));

    expect(submit).toHaveBeenCalledWith('attack-from-mars', expect.objectContaining({ note: '' }));
    expect(toast.messages).toHaveLength(1);
    const msg = toast.messages[0];
    expect(msg.text).toContain('Deleted');
    expect(msg.text).toContain('Attack from Mars');
    expect(msg.persistUntilNav).toBe(true);
    expect(msg.action?.label).toBe('Undo');
    expect(goto).toHaveBeenCalledWith('/titles');
  });

  it('undo path: invokes submitUndoDelete and updates toast on success', async () => {
    const user = userEvent.setup();
    const submit = vi.fn<Submit>().mockResolvedValue({ kind: 'ok', data: { changeset_id: 42 } });
    submitUndoDelete.mockResolvedValue({ kind: 'ok', changesetId: 42 });
    renderUnblocked(submit);

    await user.click(screen.getByRole('button', { name: 'Delete Title' }));

    const action = toast.messages[0].action;
    expect(action).toBeDefined();
    await action!.onAction();

    expect(submitUndoDelete).toHaveBeenCalledWith(42);
    expect(toast.messages[0].text).toContain('Restored');
    expect(toast.messages[0].text).toContain('Attack from Mars');
  });

  it('superseded undo: updates toast with editHistoryHref', async () => {
    const user = userEvent.setup();
    const submit = vi.fn<Submit>().mockResolvedValue({ kind: 'ok', data: { changeset_id: 42 } });
    submitUndoDelete.mockResolvedValue({
      kind: 'superseded',
      message: 'Cannot undo automatically.',
    });
    renderUnblocked(submit);

    await user.click(screen.getByRole('button', { name: 'Delete Title' }));
    await toast.messages[0].action!.onAction();

    expect(toast.messages[0].text).toBe('Cannot undo automatically.');
    expect(toast.messages[0].href).toBe('/titles/attack-from-mars/edit-history');
  });

  it('blocked state: hides Delete button and notes, renders blocked content', () => {
    const blocked: BlockedState = {
      kind: 'referrers',
      lead: "Can't delete:",
      referrers: [
        {
          entity_type: 'model',
          slug: 'medieval-madness-pro',
          name: 'Medieval Madness (Pro)',
          relation: 'system',
          blocked_target_type: 'system',
          blocked_target_slug: null,
        },
      ],
      renderReferrerHref: (r) => (r.slug ? `/models/${r.slug}` : null),
      renderReferrerHint: (r) => `references this title via ${r.relation}`,
      footer: 'Resolve these references, then try again.',
    };

    render(DeletePage<Response>, {
      entityLabel: 'Title',
      entityName: 'Attack from Mars',
      public_id: 'attack-from-mars',
      submit: vi.fn(),
      cancelHref: '/titles/attack-from-mars',
      redirectAfterDelete: '/titles',
      editHistoryHref: '/titles/attack-from-mars/edit-history',
      blocked,
      impact: makeImpact(),
    });

    expect(screen.queryByRole('button', { name: 'Delete Title' })).not.toBeInTheDocument();
    // NotesAndCitationsDetails uses a <details><summary>; its summary text
    // includes "Notes" — confirm absent in the blocked branch.
    expect(screen.queryByText(/Notes & Citations/)).not.toBeInTheDocument();
    expect(screen.getByText("Can't delete:")).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Medieval Madness (Pro)' });
    expect(link).toHaveAttribute('href', '/models/medieval-madness-pro');
    expect(screen.getByText('references this title via system')).toBeInTheDocument();
    expect(screen.getByText('Resolve these references, then try again.')).toBeInTheDocument();
  });

  it('renderReferrerHref returning null renders plain text instead of a link', () => {
    const referrer: BlockingReferrer = {
      entity_type: 'person',
      slug: null,
      name: 'Steve Ritchie',
      relation: 'designer',
      blocked_target_type: 'person',
      blocked_target_slug: null,
    };
    const blocked: BlockedState = {
      kind: 'referrers',
      lead: 'Blocked.',
      referrers: [referrer],
      renderReferrerHref: () => null,
      renderReferrerHint: () => 'references via designer',
    };

    const { container } = render(DeletePage<Response>, {
      entityLabel: 'Person',
      entityName: 'Steve Ritchie',
      public_id: 'steve-ritchie',
      submit: vi.fn(),
      cancelHref: '/people/steve-ritchie',
      redirectAfterDelete: '/people',
      editHistoryHref: '/people/steve-ritchie/edit-history',
      blocked,
      impact: makeImpact(),
    });

    expect(screen.queryByRole('link', { name: 'Steve Ritchie' })).not.toBeInTheDocument();
    // Name still renders as text inside the blocked list.
    const list = container.querySelector('section.blocked ul');
    expect(list).not.toBeNull();
    expect(within(list as HTMLElement).getByText('Steve Ritchie')).toBeInTheDocument();
  });

  it('form_error path: renders the error message in an alert', async () => {
    const user = userEvent.setup();
    const submit = vi
      .fn<Submit>()
      .mockResolvedValue({ kind: 'form_error', message: 'Could not delete record.' });
    renderUnblocked(submit);

    await user.click(screen.getByRole('button', { name: 'Delete Title' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not delete record.');
    expect(goto).not.toHaveBeenCalled();
  });
});
