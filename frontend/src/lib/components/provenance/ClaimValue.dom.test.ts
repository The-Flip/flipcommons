import { render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ClaimValueFixture from './ClaimValue.fixture.svelte';
import { _resetQualifierWarnings } from './qualifier-renderers';

describe('ClaimValue', () => {
  describe('with structured display (relationship claims)', () => {
    it('renders a two-identity claim joined with em-dash', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { person: 13, role: 9, exists: true },
          display: {
            identity: [
              { key: 'person', label: 'Pat Lawlor', state: 'resolved' },
              { key: 'role', label: 'Art', state: 'resolved' },
            ],
            qualifiers: [],
          },
        },
      });
      expect(container.textContent).toBe('Pat Lawlor — Art');
      expect(container.querySelector('s')).toBeNull();
    });

    it('strikes through when raw asserts exists:false', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { person: 13, role: 9, exists: false },
          display: {
            identity: [
              { key: 'person', label: 'Pat Lawlor', state: 'resolved' },
              { key: 'role', label: 'Art', state: 'resolved' },
            ],
            qualifiers: [],
          },
        },
      });
      const struck = container.querySelector('s');
      expect(struck).not.toBeNull();
      expect(struck!.textContent).toBe('Pat Lawlor — Art');
    });

    it('appends ×N when count > 1', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { gameplay_feature: 5, count: 3, exists: true },
          display: {
            identity: [{ key: 'gameplay_feature', label: 'Multiball', state: 'resolved' }],
            qualifiers: [{ key: 'count', value: 3 }],
          },
        },
      });
      expect(container.textContent).toBe('Multiball ×3');
    });

    it('omits the count suffix when count is 1', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { gameplay_feature: 5, count: 1, exists: true },
          display: {
            identity: [{ key: 'gameplay_feature', label: 'Multiball', state: 'resolved' }],
            qualifiers: [{ key: 'count', value: 1 }],
          },
        },
      });
      expect(container.textContent).toBe('Multiball');
    });

    it('renders identity-only when no qualifiers are present', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { theme: 7, exists: true },
          display: {
            identity: [{ key: 'theme', label: 'Horror', state: 'resolved' }],
            qualifiers: [],
          },
        },
      });
      expect(container.textContent).toBe('Horror');
    });

    it('renders category and is_primary qualifiers together', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { media_asset: 42, category: 'flyer', is_primary: true, exists: true },
          display: {
            identity: [{ key: 'media_asset', label: 'Title cover', state: 'resolved' }],
            qualifiers: [
              { key: 'category', value: 'flyer' },
              { key: 'is_primary', value: true },
            ],
          },
        },
      });
      expect(container.textContent).toBe('Title cover (flyer) [primary]');
    });

    it('omits is_primary when false', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { media_asset: 42, category: 'flyer', is_primary: false, exists: true },
          display: {
            identity: [{ key: 'media_asset', label: 'Title cover', state: 'resolved' }],
            qualifiers: [
              { key: 'category', value: 'flyer' },
              { key: 'is_primary', value: false },
            ],
          },
        },
      });
      expect(container.textContent).toBe('Title cover (flyer)');
    });

    it('omits category when null', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { media_asset: 42, category: null, is_primary: false, exists: true },
          display: {
            identity: [{ key: 'media_asset', label: 'Title cover', state: 'resolved' }],
            qualifiers: [
              { key: 'category', value: null },
              { key: 'is_primary', value: false },
            ],
          },
        },
      });
      expect(container.textContent).toBe('Title cover');
    });

    it('renders an alias identity whose label is the chosen display form', () => {
      // Backend chose `alias_display` over `alias_value`; identity key stays
      // as the identity slot (`alias_value`) while `label` carries the
      // user-facing rendering.
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { alias_value: 'the patster', alias_display: 'The Patster', exists: true },
          display: {
            identity: [{ key: 'alias_value', label: 'The Patster', state: 'resolved' }],
            qualifiers: [],
          },
        },
      });
      expect(container.textContent).toBe('The Patster');
    });

    it('renders a deleted-target identity distinctly', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { person: 99, role: 9, exists: true },
          display: {
            identity: [
              { key: 'person', label: null, state: 'deleted' },
              { key: 'role', label: 'Art', state: 'resolved' },
            ],
            qualifiers: [],
          },
        },
      });
      expect(container.textContent).toBe('(deleted) — Art');
      const dim = container.querySelector('.missing-ref');
      expect(dim).not.toBeNull();
      expect(dim!.textContent).toBe('(deleted)');
    });

    it('renders a missing identity distinctly from deleted', () => {
      const { container } = render(ClaimValueFixture, {
        value: {
          raw: { role: 9, exists: true },
          display: {
            identity: [
              { key: 'person', label: null, state: 'missing' },
              { key: 'role', label: 'Art', state: 'resolved' },
            ],
            qualifiers: [],
          },
        },
      });
      expect(container.textContent).toBe('(missing) — Art');
    });

    describe('unknown qualifier keys', () => {
      let warnSpy: ReturnType<typeof vi.spyOn>;

      beforeEach(() => {
        _resetQualifierWarnings();
        warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      });

      afterEach(() => {
        warnSpy.mockRestore();
      });

      it('renders unknown keys with default format and warns once', () => {
        const { container } = render(ClaimValueFixture, {
          value: {
            raw: { thing: 1, weirdkey: 'hello', exists: true },
            display: {
              identity: [{ key: 'thing', label: 'Widget', state: 'resolved' }],
              qualifiers: [{ key: 'weirdkey', value: 'hello' }],
            },
          },
        });
        expect(container.textContent).toBe('Widget (weirdkey: hello)');
        expect(warnSpy).toHaveBeenCalledTimes(1);
        expect(warnSpy.mock.calls[0][0]).toContain('weirdkey');
      });

      it('omits unknown keys whose value is null / false / empty', () => {
        const { container } = render(ClaimValueFixture, {
          value: {
            raw: { thing: 1, weirdkey: null, exists: true },
            display: {
              identity: [{ key: 'thing', label: 'Widget', state: 'resolved' }],
              qualifiers: [{ key: 'weirdkey', value: null }],
            },
          },
        });
        expect(container.textContent).toBe('Widget');
      });
    });
  });

  describe('without display (simplify fallback)', () => {
    it('renders a single-string-key claim as the bare scalar', () => {
      const { container } = render(ClaimValueFixture, {
        value: { raw: { value: 'DW', exists: true } },
      });
      expect(container.textContent).toBe('DW');
      expect(container.querySelector('s')).toBeNull();
    });

    it('strikes through a negative single-string-key claim', () => {
      const { container } = render(ClaimValueFixture, {
        value: { raw: { value: 'DW', exists: false } },
      });
      const struck = container.querySelector('s');
      expect(struck).not.toBeNull();
      expect(struck!.textContent).toBe('DW');
    });
  });

  describe('without display or simplify (formatValue fallback)', () => {
    it('renders bare scalars verbatim', () => {
      const { container } = render(ClaimValueFixture, { value: { raw: 'solid-state' } });
      expect(container.textContent).toBe('solid-state');
    });

    it('renders null raw as em-dash', () => {
      const { container } = render(ClaimValueFixture, { value: { raw: null } });
      expect(container.textContent).toBe('—');
    });

    it('renders a null/undefined value prop as em-dash', () => {
      const cases: (null | undefined)[] = [null, undefined];
      for (const value of cases) {
        const { container } = render(ClaimValueFixture, { value });
        expect(container.textContent).toBe('—');
      }
    });

    it('JSON-stringifies unrecognised dict shapes', () => {
      const { container } = render(ClaimValueFixture, {
        value: { raw: { person: 13, role: 9, exists: true } },
      });
      expect(container.textContent).toBe('{"person":13,"role":9,"exists":true}');
    });
  });
});
