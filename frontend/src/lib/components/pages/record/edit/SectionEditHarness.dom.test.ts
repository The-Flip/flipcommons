import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SectionEditHarnessFixture from './SectionEditHarness.fixture.svelte';

const { goto } = vi.hoisted(() => ({ goto: vi.fn() }));
const { toastSuccess } = vi.hoisted(() => ({ toastSuccess: vi.fn() }));

vi.mock('$app/navigation', () => ({ goto, invalidateAll: vi.fn() }));
vi.mock('$app/paths', () => ({ resolve: (url: string) => url }));
vi.mock('$lib/toast/toast.svelte', () => ({
  toast: { success: toastSuccess, info: vi.fn(), error: vi.fn() },
}));

describe('SectionEditHarness', () => {
  beforeEach(() => {
    goto.mockReset();
    toastSuccess.mockReset();
  });

  it('gates Save on the editor dirty state and mirrors it to the nav-lock', async () => {
    const user = userEvent.setup();
    render(SectionEditHarnessFixture);

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
    expect(screen.getByTestId('context-dirty')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Make dirty' }));
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByTestId('context-dirty')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Make clean' }));
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByTestId('context-dirty')).toHaveTextContent('false');
  });

  it('cancels to the detail page without confirming when clean', async () => {
    const user = userEvent.setup();
    render(SectionEditHarnessFixture);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(goto).toHaveBeenCalledTimes(1);
  });

  it('confirms before cancelling a dirty editor and stays put when declined', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(SectionEditHarnessFixture);

    await user.click(screen.getByRole('button', { name: 'Make dirty' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(confirmSpy).toHaveBeenCalledWith('Discard unsaved changes?');
    expect(goto).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('toasts, runs the onsaved hook and resets to clean after a save', async () => {
    const user = userEvent.setup();
    const onsaved = vi.fn();
    render(SectionEditHarnessFixture, { props: { onsaved } });

    await user.click(screen.getByRole('button', { name: 'Make dirty' }));
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();

    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Saved.'));
    expect(onsaved).toHaveBeenCalledTimes(1);
    // The editor remounts clean after save, so Save disables again.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled());
    expect(screen.getByTestId('context-dirty')).toHaveTextContent('false');
  });

  it('renders the immediate editor with a Done button for non-form sections', async () => {
    const user = userEvent.setup();
    render(SectionEditHarnessFixture, { props: { usesSectionEditorForm: false } });

    expect(screen.getByTestId('immediate-body')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(goto).toHaveBeenCalledTimes(1);
  });
});
