import { describe, expect, it } from 'vitest';

import { PRODUCED_SLUG, showsProductionStatus } from './production-status';

describe('showsProductionStatus', () => {
  it('shows a non-produced status', () => {
    expect(showsProductionStatus({ name: 'Unreleased', public_id: 'unreleased' })).toBe(true);
  });

  it('hides the produced status (the code-anchored value)', () => {
    expect(showsProductionStatus({ name: 'Produced', public_id: PRODUCED_SLUG })).toBe(false);
  });

  it('hides null/undefined', () => {
    expect(showsProductionStatus(null)).toBe(false);
    expect(showsProductionStatus(undefined)).toBe(false);
  });
});
