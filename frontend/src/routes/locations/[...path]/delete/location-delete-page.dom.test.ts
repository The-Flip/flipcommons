import { render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { goto, resolve } = vi.hoisted(() => ({
  goto: vi.fn(),
  resolve: vi.fn((url: string) => url),
}));

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/paths', () => ({ resolve }));
vi.mock('$lib/undo-delete', () => ({ submitUndoDelete: vi.fn() }));
vi.mock('./location-delete', () => ({ submitDelete: vi.fn() }));

import Page from './+page@.svelte';

type Preview = {
  name: string;
  changeset_count: number;
  blocked_by?: { entity_type: string; name: string; public_id: string; relation: string }[];
  active_children_count?: number;
};

function renderPage(public_id: string, preview: Preview) {
  // The route's loader returns { preview, public_id }; mirror that shape.
  return render(Page, {
    data: { preview, public_id },
  } as unknown as Parameters<typeof render>[1]);
}

beforeEach(() => {
  goto.mockReset();
});

describe('Location delete page', () => {
  it('renders the unblocked state with the standard delete button when nothing references the location', () => {
    renderPage('usa/il/chicago', {
      name: 'Chicago',
      changeset_count: 4,
      blocked_by: [],
      active_children_count: 0,
    });

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/Delete .*Chicago/i);
    expect(screen.getByRole('button', { name: 'Delete Location' })).toBeInTheDocument();
    // No blocked-state messaging.
    expect(screen.queryByText(/active child location/i)).toBeNull();
    expect(screen.queryByText(/can't be deleted because/i)).toBeNull();
  });

  it('renders the active-children blocked state when active_children_count > 0', () => {
    renderPage('usa', {
      name: 'United States',
      changeset_count: 2,
      blocked_by: [],
      active_children_count: 3,
    });

    expect(
      screen.getByText(/United States has 3 active child locations\. Delete those first\./i),
    ).toBeInTheDocument();
    // Blocked: the primary delete button is hidden.
    expect(screen.queryByRole('button', { name: 'Delete Location' })).toBeNull();
  });

  it('renders the CEL-referrer blocked state with corporate-entity hrefs when blocked_by has rows', () => {
    renderPage('usa/il/chicago', {
      name: 'Chicago',
      changeset_count: 1,
      active_children_count: 0,
      blocked_by: [
        {
          entity_type: 'corporate-entity',
          name: 'Williams Electronics',
          public_id: 'williams-electronics',
          relation: 'corporate_entity_location',
        },
      ],
    });

    expect(
      screen.getByText(
        /This location can't be deleted because active corporate-entity locations still point at it/i,
      ),
    ).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Williams Electronics' });
    expect(link).toHaveAttribute('href', '/corporate-entities/williams-electronics');
    // No primary delete button while blocked.
    expect(screen.queryByRole('button', { name: 'Delete Location' })).toBeNull();
  });
});
