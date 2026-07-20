import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import type { EntityRef } from '$lib/api/schema';
import { makeModelDetail } from '$lib/api/detail-fixtures';
import ModelSpecsSidebar from './ModelSpecsSidebar.svelte';

function renderWith(production_status: EntityRef | null) {
  render(ModelSpecsSidebar, { props: { model: makeModelDetail({ production_status }) } });
}

describe('ModelSpecsSidebar production status', () => {
  it('shows a non-produced status as a link to its page', () => {
    renderWith({ name: 'Unreleased', public_id: 'unreleased' });

    expect(screen.getByText('Production status')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Unreleased' })).toHaveAttribute(
      'href',
      '/production-statuses/unreleased',
    );
  });

  it('hides the produced status', () => {
    renderWith({ name: 'Produced', public_id: 'produced' });

    expect(screen.queryByText('Production status')).toBeNull();
  });

  it('hides a null status', () => {
    renderWith(null);

    expect(screen.queryByText('Production status')).toBeNull();
  });
});

describe('ModelSpecsSidebar manufacturer model id', () => {
  it('shows the manufacturer model id as plain text', () => {
    render(ModelSpecsSidebar, {
      props: { model: makeModelDetail({ manufacturer_model_identifier: '500-5013-01' }) },
    });

    expect(screen.getByText('Manufacturer Model ID')).toBeInTheDocument();
    expect(screen.getByText('500-5013-01')).toBeInTheDocument();
  });

  it('hides the row when absent', () => {
    render(ModelSpecsSidebar, { props: { model: makeModelDetail({}) } });

    expect(screen.queryByText('Manufacturer Model ID')).toBeNull();
  });
});
