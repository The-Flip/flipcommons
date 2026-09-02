import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import {
  buildFullTitle,
  entityPageTitle,
  metaDescriptionFor,
  truncateMetaDescription,
  truncateOgDescription,
  buildCanonicalUrl,
  DEFAULT_SOCIAL_IMAGE,
} from './meta-tags';
import { SITE_NAME, SITE_TITLE } from '$lib/constants';

describe('buildFullTitle', () => {
  test('appends site title suffix', () => {
    expect(buildFullTitle('Medieval Madness')).toBe(`Medieval Madness — ${SITE_TITLE}`);
  });

  test('does not double site title', () => {
    expect(buildFullTitle(SITE_TITLE)).toBe(SITE_TITLE);
  });
});

describe('entityPageTitle', () => {
  const sections = [
    { segment: 'name', label: 'Name' },
    { segment: 'external-data', label: 'External Data' },
  ];

  test('leaves the detail page title bare', () => {
    expect(entityPageTitle('Earthshaker', '/models/earthshaker', '/models/earthshaker')).toBe(
      'Earthshaker',
    );
  });

  test('tolerates a trailing slash on the detail page', () => {
    expect(entityPageTitle('Earthshaker', '/models/earthshaker/', '/models/earthshaker')).toBe(
      'Earthshaker',
    );
  });

  test('qualifies the edit-history sub-route', () => {
    expect(
      entityPageTitle('Earthshaker', '/models/earthshaker/edit-history', '/models/earthshaker'),
    ).toBe('Earthshaker • Edit History');
  });

  test('qualifies the sources sub-route', () => {
    expect(
      entityPageTitle('Earthshaker', '/models/earthshaker/sources', '/models/earthshaker'),
    ).toBe('Earthshaker • Sources');
  });

  test('names the section being edited', () => {
    expect(
      entityPageTitle(
        'Earthshaker',
        '/models/earthshaker/edit/external-data',
        '/models/earthshaker',
        sections,
      ),
    ).toBe('Earthshaker • Edit External Data');
  });

  test('falls back to a bare "Edit" for an unknown section', () => {
    expect(
      entityPageTitle(
        'Earthshaker',
        '/models/earthshaker/edit/nope',
        '/models/earthshaker',
        sections,
      ),
    ).toBe('Earthshaker • Edit');
    expect(
      entityPageTitle('Earthshaker', '/models/earthshaker/edit', '/models/earthshaker', sections),
    ).toBe('Earthshaker • Edit');
  });

  test('reads the sub-route relative to the record, so multi-segment paths work', () => {
    expect(
      entityPageTitle(
        'Illinois',
        '/locations/united-states/illinois/sources',
        '/locations/united-states/illinois',
      ),
    ).toBe('Illinois • Sources');
  });

  test('does not mistake a record slugged like a sub-route for one', () => {
    expect(entityPageTitle('Sources', '/titles/sources', '/titles/sources')).toBe('Sources');
  });

  test('ignores sub-routes it has no title for', () => {
    expect(
      entityPageTitle('Earthshaker', '/models/earthshaker/delete', '/models/earthshaker'),
    ).toBe('Earthshaker');
  });
});

describe('metaDescriptionFor', () => {
  test('sources the clean .plain text, not raw .text markdown', () => {
    const profile = {
      name: 'Multiball',
      description: {
        plain: 'A mode where multiple balls are in play at once.',
        text: 'A mode where **multiple balls** are in play, see [[tag:multiball]].',
      },
    };
    expect(metaDescriptionFor(profile)).toBe('A mode where multiple balls are in play at once.');
  });

  test('falls back to "{name} — {SITE_NAME}" when .plain is empty', () => {
    const profile = { name: 'Multiball', description: { plain: '' } };
    expect(metaDescriptionFor(profile)).toBe(`Multiball — ${SITE_NAME}`);
  });

  test('uses a caller-supplied fallback when .plain is empty', () => {
    const profile = { name: 'Pat Lawlor', description: { plain: '' } };
    expect(metaDescriptionFor(profile, 'Pat Lawlor — pinball industry professional')).toBe(
      'Pat Lawlor — pinball industry professional',
    );
  });

  test('prefers .plain over the caller-supplied fallback when both exist', () => {
    const profile = { name: 'Pat Lawlor', description: { plain: 'Designer of many classics.' } };
    expect(metaDescriptionFor(profile, 'unused fallback')).toBe('Designer of many classics.');
  });

  test('returns untruncated prose (MetaTags owns the length budgets)', () => {
    const long = 'word '.repeat(100).trim();
    const profile = { name: 'X', description: { plain: long } };
    const result = metaDescriptionFor(profile);
    expect(result).toBe(long);
    expect(result).not.toContain('…');
  });
});

describe('truncateMetaDescription', () => {
  test('short description passes through unchanged', () => {
    expect(truncateMetaDescription('A short description.')).toBe('A short description.');
  });

  test('exactly 155 chars passes through unchanged', () => {
    const desc = 'x'.repeat(155);
    expect(truncateMetaDescription(desc)).toBe(desc);
  });

  test('truncates at 154 chars with ellipsis', () => {
    const desc = 'x'.repeat(200);
    const result = truncateMetaDescription(desc);
    expect(result).toHaveLength(155);
    expect(result).toBe('x'.repeat(154) + '\u2026');
  });
});

describe('truncateOgDescription', () => {
  test('short description passes through unchanged', () => {
    expect(truncateOgDescription('A short description.')).toBe('A short description.');
  });

  test('exactly 200 chars passes through unchanged', () => {
    const desc = 'x'.repeat(200);
    expect(truncateOgDescription(desc)).toBe(desc);
  });

  test('truncates at 199 chars with ellipsis', () => {
    const desc = 'x'.repeat(250);
    const result = truncateOgDescription(desc);
    expect(result).toHaveLength(200);
    expect(result).toBe('x'.repeat(199) + '\u2026');
  });
});

describe('buildCanonicalUrl', () => {
  test('strips query params', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo?ref=twitter')).toBe(
      'https://example.com/models/foo',
    );
  });

  test('strips hash', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo#section')).toBe(
      'https://example.com/models/foo',
    );
  });

  test('strips both query and hash', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo?a=1#top')).toBe(
      'https://example.com/models/foo',
    );
  });

  test('clean URL passes through unchanged', () => {
    expect(buildCanonicalUrl('https://example.com/models/foo')).toBe(
      'https://example.com/models/foo',
    );
  });
});

/** Read a PNG's pixel dimensions from its IHDR chunk (width @ byte 16, height @ 20, big-endian). */
function pngDimensions(staticPath: string): { width: number; height: number } {
  const file = fileURLToPath(new URL(`../../../../../../static${staticPath}`, import.meta.url));
  const buf = readFileSync(file);
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

describe('default social image asset', () => {
  // The declared dimensions are emitted verbatim as og:image:width/height, so
  // they must agree with the asset on disk — assert the file matches rather
  // than restating the literals (which would only mirror the source). The
  // readFileSync also fails loudly if the asset goes missing.
  test('asset matches the declared 1200×630', () => {
    expect(DEFAULT_SOCIAL_IMAGE).toMatchObject({ width: 1200, height: 630, type: 'image/png' });
    expect(pngDimensions(DEFAULT_SOCIAL_IMAGE.path)).toEqual({
      width: DEFAULT_SOCIAL_IMAGE.width,
      height: DEFAULT_SOCIAL_IMAGE.height,
    });
  });

  test('carries branded alt text', () => {
    expect(DEFAULT_SOCIAL_IMAGE.alt).toContain(SITE_NAME);
  });
});
