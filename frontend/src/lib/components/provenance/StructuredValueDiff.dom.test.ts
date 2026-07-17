import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { FieldChangeSchema } from '$lib/api/schema';
import StructuredValueDiff from './StructuredValueDiff.svelte';
import { buildStructuredDiff } from './change-display';

describe('StructuredValueDiff', () => {
  it('strikes only the changed relationship member', () => {
    const change: FieldChangeSchema = {
      field_name: 'model_relationship',
      claim_key: 'model_relationship:42',
      old_value: {
        raw: {
          target_machine: 42,
          target_label: '',
          relationship_type: 'copy',
          license_status: 'unknown',
          exists: true,
        },
        display: {
          kind: 'relationship',
          identity: [
            { key: 'target_machine', label: 'Speakeasy (Playmatic, 1982)', state: 'resolved' },
          ],
          qualifiers: [
            { key: 'relationship_type', value: 'copy' },
            { key: 'license_status', value: 'unknown' },
          ],
        },
      },
      new_value: {
        raw: {
          target_machine: 42,
          target_label: '',
          relationship_type: 'copy',
          license_status: 'unlicensed',
          exists: true,
        },
        display: {
          kind: 'relationship',
          identity: [
            { key: 'target_machine', label: 'Speakeasy (Playmatic, 1982)', state: 'resolved' },
          ],
          qualifiers: [
            { key: 'relationship_type', value: 'copy' },
            { key: 'license_status', value: 'unlicensed' },
          ],
        },
      },
    };

    const parts = buildStructuredDiff(change)!;
    const { container } = render(StructuredValueDiff, { parts });

    expect(container.querySelector('.structured-diff')).not.toBeNull();
    expect(container.querySelector('del')?.textContent).toBe('Unknown');
    expect(container.querySelector('ins')?.textContent).toBe('Unlicensed');
    expect(container.querySelector('del')?.textContent).not.toContain('Speakeasy');
    expect(container.textContent?.match(/Speakeasy/g)).toHaveLength(1);
    expect(container.textContent?.match(/Copy/g)).toHaveLength(1);
  });

  it('renders a newly created relationship with the same member formatting', () => {
    const change: FieldChangeSchema = {
      field_name: 'model_relationship',
      claim_key: 'model_relationship:42',
      old_value: null,
      new_value: {
        raw: {
          target_machine: 42,
          target_label: '',
          relationship_type: 'copy',
          license_status: 'unlicensed',
          exists: true,
        },
        display: {
          kind: 'relationship',
          identity: [
            { key: 'target_machine', label: 'Speakeasy (Bally, 1982)', state: 'resolved' },
          ],
          qualifiers: [
            { key: 'relationship_type', value: 'copy' },
            { key: 'license_status', value: 'unlicensed' },
          ],
        },
      },
    };

    const parts = buildStructuredDiff(change)!;
    const { container } = render(StructuredValueDiff, { parts });

    expect(container.textContent).toContain('Target machine Speakeasy (Bally, 1982)');
    expect(container.textContent).toContain('Relationship type Copy');
    expect(container.textContent).toContain('License status Unlicensed');
    expect(container.querySelector('del')).toBeNull();
    expect(container.querySelector('ins')).toBeNull();
  });
});
