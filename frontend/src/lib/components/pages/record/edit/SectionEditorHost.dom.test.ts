import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SectionEditorHostFixture from './SectionEditorHost.fixture.svelte';

describe('SectionEditorHost', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('opens the form modal when editingKey is set to a form section', async () => {
    const user = userEvent.setup();
    render(SectionEditorHostFixture);

    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Open overview' }));

    expect(screen.getByRole('dialog', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByText('fake editor: overview')).toBeInTheDocument();
  });

  it('renders the immediate-editor base modal for non-form sections', async () => {
    const user = userEvent.setup();
    render(SectionEditorHostFixture);

    await user.click(screen.getByRole('button', { name: 'Open media' }));

    expect(screen.getByRole('dialog', { name: 'Media' })).toBeInTheDocument();
    expect(screen.getByTestId('immediate-editor')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument();
    // No Save/Cancel from SectionEditorForm
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
  });

  it('clears editingKey when the editor reports onsaved (Save flow)', async () => {
    const user = userEvent.setup();
    render(SectionEditorHostFixture);

    await user.click(screen.getByRole('button', { name: 'Open overview' }));
    expect(screen.getByTestId('editing-key')).toHaveTextContent('overview');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('editing-key')).toHaveTextContent('none');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('surfaces editor onerror messages and keeps the modal open', async () => {
    const user = userEvent.setup();
    render(SectionEditorHostFixture);

    await user.click(screen.getByRole('button', { name: 'Open features' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText('save failed for features')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Features' })).toBeInTheDocument();
  });

  it('confirms before discarding dirty edits on close, and aborts on cancel', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.fn().mockReturnValue(false);
    vi.stubGlobal('confirm', confirmSpy);

    render(SectionEditorHostFixture);

    await user.click(screen.getByRole('button', { name: 'Open overview' }));
    await user.click(screen.getByRole('button', { name: 'Make dirty' }));

    // Click the modal's Cancel button to close (which calls onclose → triggers guard)
    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(confirmSpy).toHaveBeenCalledWith('Discard unsaved changes?');
    expect(screen.getByRole('dialog', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByTestId('editing-key')).toHaveTextContent('overview');
  });

  it('discards dirty edits on close when confirmed', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));

    render(SectionEditorHostFixture);

    await user.click(screen.getByRole('button', { name: 'Open overview' }));
    await user.click(screen.getByRole('button', { name: 'Make dirty' }));
    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('editing-key')).toHaveTextContent('none');
  });
});
