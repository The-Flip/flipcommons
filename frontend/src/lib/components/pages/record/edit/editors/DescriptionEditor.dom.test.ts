import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/api/link-types', async () => {
  const f = await import('$lib/components/input/link-types-fixtures');
  return {
    fetchLinkTypes: vi.fn().mockResolvedValue(f.LINK_TYPES),
    searchLinkTargets: vi.fn().mockResolvedValue({ results: f.SEARCH_RESULTS }),
  };
});

import DescriptionEditorFixture from './DescriptionEditor.fixture.svelte';

describe('DescriptionEditor', () => {
  it('reports clean state initially and dirty state after editing', async () => {
    const user = userEvent.setup();
    render(DescriptionEditorFixture);

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('false');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('false');

    await user.type(screen.getByLabelText('Description'), ' updated');

    expect(screen.getByTestId('dirty-callback')).toHaveTextContent('true');

    await user.click(screen.getByRole('button', { name: 'Check dirty' }));
    expect(screen.getByTestId('dirty-handle')).toHaveTextContent('true');
  });

  it('calls the injected save function with the edited description when dirty', async () => {
    const user = userEvent.setup();
    render(DescriptionEditorFixture);

    await user.type(screen.getByLabelText('Description'), ' updated');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent(
      JSON.stringify({
        fields: { description: 'Original description updated' },
        inline_citations: [],
      }),
    );
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });

  it('skips the save call when clean', async () => {
    const user = userEvent.setup();
    render(DescriptionEditorFixture);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByTestId('last-save-body')).toHaveTextContent('null');
    expect(screen.getByTestId('saved-count')).toHaveTextContent('1');
  });
});
