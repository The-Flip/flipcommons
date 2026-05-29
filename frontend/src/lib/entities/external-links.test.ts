import { describe, it, expect } from 'vitest';
import { buildSchemaOrgNode, type EntityBaseFacts } from './schema-org';
import { externalLinks } from './external-links';
import type { EntityInfo } from './types';

/**
 * Self-contained fakes so these exercise the generic externalRefs machinery
 * (the `externalLinks()` UI helper and the JSON-LD assembler) without coupling
 * to any real per-entity declaration.
 */
interface FakeSchema extends EntityBaseFacts {
  ipdb?: number | null;
  pinside?: string | null;
  opdb?: string | null;
}

function makeInfo(externalRefs: EntityInfo<FakeSchema>['externalRefs']): EntityInfo<FakeSchema> {
  return { entityType: 'model', schemaOrg: { types: ['Game'] }, externalRefs };
}

function baseEntity(overrides: Partial<FakeSchema> = {}): FakeSchema {
  return {
    name: 'Test Entity',
    public_id: 'test-entity',
    last_modified: '2024-01-01T00:00:00Z',
    description: { plain: '', html: '', text: '' } as FakeSchema['description'],
    ...overrides,
  };
}

const PAGE_URL = new URL('https://flipcommons.test/models/test-entity');

const REGISTRY: EntityInfo<FakeSchema>['externalRefs'] = {
  ipdb: { label: 'IPDB', urlTemplate: 'https://www.ipdb.org/machine.cgi?id={id}' },
  pinside: { label: 'Pinside', urlTemplate: 'https://pinside.com/pinball/machine/{id}' },
  opdb: { identifier: 'OPDB' },
};

describe('externalLinks', () => {
  it('substitutes {id} and returns label + href for resolvable entries with a value', () => {
    const links = externalLinks(
      baseEntity({ ipdb: 1384, pinside: 'godzilla-pro' }),
      makeInfo(REGISTRY),
    );
    expect(links).toEqual([
      { label: 'IPDB', href: 'https://www.ipdb.org/machine.cgi?id=1384' },
      { label: 'Pinside', href: 'https://pinside.com/pinball/machine/godzilla-pro' },
    ]);
  });

  it('excludes identifier-only entries (no resolvable URL)', () => {
    const links = externalLinks(baseEntity({ opdb: 'G50L9-MDxXD' }), makeInfo(REGISTRY));
    expect(links).toEqual([]);
  });

  it('skips entries whose value is null/undefined/empty', () => {
    const links = externalLinks(baseEntity({ ipdb: null, pinside: '' }), makeInfo(REGISTRY));
    expect(links).toEqual([]);
  });

  it('preserves declaration order', () => {
    const links = externalLinks(baseEntity({ pinside: 'x', ipdb: 7 }), makeInfo(REGISTRY));
    expect(links.map((l) => l.label)).toEqual(['IPDB', 'Pinside']);
  });

  it('returns [] when no externalRefs are declared', () => {
    const info: EntityInfo<FakeSchema> = { entityType: 'model', schemaOrg: { types: ['Game'] } };
    expect(externalLinks(baseEntity({ ipdb: 7 }), info)).toEqual([]);
  });
});

describe('buildSchemaOrgNode externalRefs', () => {
  it('emits resolvable IDs as a sameAs array with {id} substituted', () => {
    const node = buildSchemaOrgNode(
      baseEntity({ ipdb: 1384, pinside: 'godzilla-pro' }),
      makeInfo(REGISTRY),
      PAGE_URL,
    );
    expect(node.sameAs).toEqual([
      'https://www.ipdb.org/machine.cgi?id=1384',
      'https://pinside.com/pinball/machine/godzilla-pro',
    ]);
  });

  it('emits sameAs as an array even for a single value (byte-stable @graph)', () => {
    const node = buildSchemaOrgNode(baseEntity({ ipdb: 1384 }), makeInfo(REGISTRY), PAGE_URL);
    expect(node.sameAs).toEqual(['https://www.ipdb.org/machine.cgi?id=1384']);
    expect(Array.isArray(node.sameAs)).toBe(true);
  });

  it('emits non-resolvable IDs as identifier PropertyValues', () => {
    const node = buildSchemaOrgNode(
      baseEntity({ opdb: 'G50L9-MDxXD' }),
      makeInfo(REGISTRY),
      PAGE_URL,
    );
    expect(node.identifier).toEqual([
      { '@type': 'PropertyValue', propertyID: 'OPDB', value: 'G50L9-MDxXD' },
    ]);
    expect(node.sameAs).toBeUndefined();
  });

  it('emits both sameAs and identifier on a node with mixed entries', () => {
    const node = buildSchemaOrgNode(
      baseEntity({ ipdb: 1384, opdb: 'G50L9-MDxXD' }),
      makeInfo(REGISTRY),
      PAGE_URL,
    );
    expect(node.sameAs).toEqual(['https://www.ipdb.org/machine.cgi?id=1384']);
    expect(node.identifier).toEqual([
      { '@type': 'PropertyValue', propertyID: 'OPDB', value: 'G50L9-MDxXD' },
    ]);
  });

  it('skips null/undefined/empty values, emitting neither key', () => {
    const node = buildSchemaOrgNode(
      baseEntity({ ipdb: null, pinside: '', opdb: undefined }),
      makeInfo(REGISTRY),
      PAGE_URL,
    );
    expect(node.sameAs).toBeUndefined();
    expect(node.identifier).toBeUndefined();
  });
});
