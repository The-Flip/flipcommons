import { describe, expect, test } from 'vitest';
import { buildSchemaOrgNode, buildEntityJsonLd, type EntityBaseFacts } from './schema-org';
import type { EntityInfo, SchemaOrgInfo } from './types';
import { creditRole, manufacturer, system, theme } from './index';

const ORIGIN = 'https://flipcommons.org';
const PAGE = new URL(`${ORIGIN}/themes/fantasy`);

function entity(over: Partial<EntityBaseFacts> = {}): EntityBaseFacts {
  return {
    name: 'Fantasy',
    public_id: 'fantasy',
    last_modified: '2026-05-29T16:12:08.340Z',
    description: { text: '', html: '', plain: 'Dragons and wizards.', citations: [] },
    ...over,
  };
}

function info(
  schemaOrg: EntityInfo<EntityBaseFacts>['schemaOrg'],
  entityType: EntityInfo<EntityBaseFacts>['entityType'] = 'theme',
): EntityInfo<EntityBaseFacts> {
  return { entityType, schemaOrg };
}

/**
 * Build a node from a loosely-typed entity + schemaOrg, so tests can exercise
 * `fieldMap`/`relationshipMap` keys (e.g. `logo_url`, `manufacturer`) that
 * aren't on `EntityBaseFacts`. The casts are localized to this harness.
 */
function buildNode(
  ent: Record<string, unknown>,
  schemaOrg: SchemaOrgInfo<Record<string, unknown>>,
  entityType: EntityInfo<EntityBaseFacts>['entityType'] = 'theme',
  page: URL = PAGE,
) {
  return buildSchemaOrgNode(
    ent as unknown as EntityBaseFacts,
    { entityType, schemaOrg } as unknown as EntityInfo<EntityBaseFacts>,
    page,
  );
}

describe('buildSchemaOrgNode', () => {
  test('single type emits @type as a string', () => {
    const node = buildSchemaOrgNode(entity(), info({ types: ['DefinedTerm'] }), PAGE);
    expect(node['@type']).toBe('DefinedTerm');
    expect(node.name).toBe('Fantasy');
    expect(node.description).toBe('Dragons and wizards.');
  });

  test('emits dateModified from last_modified (ISO string, as-is)', () => {
    const node = buildSchemaOrgNode(
      entity({ last_modified: '2026-05-29T16:12:08.340Z' }),
      info({ types: ['DefinedTerm'] }),
      PAGE,
    );
    expect(node.dateModified).toBe('2026-05-29T16:12:08.340Z');
  });

  test('omits dateModified when last_modified is empty', () => {
    const node = buildSchemaOrgNode(
      entity({ last_modified: '' }),
      info({ types: ['DefinedTerm'] }),
      PAGE,
    );
    expect(node.dateModified).toBeUndefined();
  });

  test('multiple types emit @type as an array', () => {
    const node = buildSchemaOrgNode(entity(), info({ types: ['Game', 'ProductModel'] }), PAGE);
    expect(node['@type']).toEqual(['Game', 'ProductModel']);
  });

  test('function-form types are evaluated against the entity', () => {
    const node = buildSchemaOrgNode(
      entity({ public_id: 'sci-fi' }),
      info({ types: (e) => (e.public_id === 'sci-fi' ? ['DefinedTerm'] : ['Thing']) }),
      PAGE,
    );
    expect(node['@type']).toBe('DefinedTerm');
  });

  test('@id is the canonical /{plural}/{public_id} URL, independent of the page path', () => {
    const node = buildSchemaOrgNode(
      entity(),
      info({ types: ['DefinedTerm'] }),
      new URL(`${ORIGIN}/themes/fantasy/sources`),
    );
    expect(node['@id']).toBe(`${ORIGIN}/themes/fantasy`);
  });

  test('@id uses the entity_type_plural of the declared entityType', () => {
    const node = buildSchemaOrgNode(
      entity({ public_id: 'design' }),
      info({ types: ['Occupation'] }, 'credit-role'),
      PAGE,
    );
    expect(node['@id']).toBe(`${ORIGIN}/credit-roles/design`);
  });

  test('@id uses the full public_id path (Location), not a collapsed last segment', () => {
    const node = buildSchemaOrgNode(
      entity({ public_id: 'usa/il/chicago', name: 'Chicago' }),
      info({ types: ['City'] }, 'location'),
      new URL(`${ORIGIN}/locations/usa/il/chicago`),
    );
    expect(node['@id']).toBe(`${ORIGIN}/locations/usa/il/chicago`);
  });

  test('description is omitted when .plain is empty', () => {
    const node = buildSchemaOrgNode(
      entity({ description: { text: '', html: '', plain: '', citations: [] } }),
      info({ types: ['DefinedTerm'] }),
      PAGE,
    );
    expect(node).not.toHaveProperty('description');
  });

  test('description is omitted when .plain is only whitespace', () => {
    const node = buildSchemaOrgNode(
      entity({ description: { text: '', html: '', plain: '   ', citations: [] } }),
      info({ types: ['DefinedTerm'] }),
      PAGE,
    );
    expect(node).not.toHaveProperty('description');
  });
});

describe('buildEntityJsonLd', () => {
  test('emits a @graph of the entity node plus a Home › name breadcrumb', () => {
    const graph = buildEntityJsonLd(entity(), info({ types: ['DefinedTerm'] }), PAGE);
    expect(graph['@context']).toBe('https://schema.org');
    const nodes = graph['@graph'] as Record<string, unknown>[];
    expect(nodes).toHaveLength(2);

    expect(nodes[0]['@id']).toBe(`${ORIGIN}/themes/fantasy`);

    const crumb = nodes[1];
    expect(crumb['@type']).toBe('BreadcrumbList');
    const items = crumb.itemListElement as Record<string, unknown>[];
    expect(items.map((i) => i.name)).toEqual(['Home', 'Fantasy']);
    expect(items[0].item).toBe(`${ORIGIN}/`);
    expect(items[1].item).toBe(`${ORIGIN}/themes/fantasy`);
  });
});

describe('fieldMap', () => {
  test('maps source fields to their schema.org property names', () => {
    const node = buildNode(
      { ...entity(), logo_url: 'https://cdn.example/logo.png', website: 'https://stern.example' },
      { types: ['Brand'], fieldMap: { logo_url: 'logo', website: 'url' } },
      'manufacturer',
    );
    expect(node.logo).toBe('https://cdn.example/logo.png');
    expect(node.url).toBe('https://stern.example');
  });

  test('null or empty source values are dropped', () => {
    const node = buildNode(
      { ...entity(), logo_url: null, website: '' },
      { types: ['Brand'], fieldMap: { logo_url: 'logo', website: 'url' } },
      'manufacturer',
    );
    expect(node).not.toHaveProperty('logo');
    expect(node).not.toHaveProperty('url');
  });
});

describe('relationshipMap (single FK)', () => {
  test('emits a single @id ref using the target entity_type_plural', () => {
    const node = buildNode(
      { ...entity({ public_id: 'spike-2' }), manufacturer: { name: 'Stern', public_id: 'stern' } },
      { types: ['CreativeWork'], relationshipMap: { manufacturer: 'producer' } },
      'system',
    );
    // /manufacturers/, not /systems/ — the target's plural, not the subject's.
    expect(node.producer).toEqual({ '@id': `${ORIGIN}/manufacturers/stern` });
  });

  test('a null ref drops the property', () => {
    const node = buildNode(
      { ...entity(), manufacturer: null },
      { types: ['CreativeWork'], relationshipMap: { manufacturer: 'producer' } },
      'system',
    );
    expect(node).not.toHaveProperty('producer');
  });
});

describe('relationshipMap (many)', () => {
  test('emits an array of @id refs', () => {
    const node = buildNode(
      {
        ...entity(),
        parents: [
          { name: 'Solid State', public_id: 'solid-state' },
          { name: 'Electromechanical', public_id: 'em' },
        ],
      },
      { types: ['DefinedTerm'], relationshipMap: { parents: 'isPartOf' } },
      'theme',
    );
    expect(node.isPartOf).toEqual([
      { '@id': `${ORIGIN}/themes/solid-state` },
      { '@id': `${ORIGIN}/themes/em` },
    ]);
  });

  test('an empty list drops the property', () => {
    const node = buildNode(
      { ...entity(), parents: [] },
      { types: ['DefinedTerm'], relationshipMap: { parents: 'isPartOf' } },
      'theme',
    );
    expect(node).not.toHaveProperty('isPartOf');
  });
});

describe('relationshipMap guard', () => {
  test('mapping a non-relationship (scalar) field throws', () => {
    expect(() =>
      buildNode(
        { ...entity() },
        { types: ['DefinedTerm'], relationshipMap: { name: 'producer' } },
        'theme',
      ),
    ).toThrow(/not a declared relationship/);
  });
});

describe('per-model declarations', () => {
  test('theme is a DefinedTerm', () => {
    expect(theme.entityType).toBe('theme');
    expect(theme.schemaOrg.types).toEqual(['DefinedTerm']);
  });

  test('credit-role is an Occupation', () => {
    expect(creditRole.entityType).toBe('credit-role');
    expect(creditRole.schemaOrg.types).toEqual(['Occupation']);
  });

  test('manufacturer is a Brand with a logo/url fieldMap', () => {
    expect(manufacturer.entityType).toBe('manufacturer');
    expect(manufacturer.schemaOrg.types).toEqual(['Brand']);
    expect(manufacturer.schemaOrg.fieldMap).toEqual({ logo_url: 'logo', website: 'url' });
  });

  test('system is a CreativeWork mapping manufacturer → producer', () => {
    expect(system.entityType).toBe('system');
    expect(system.schemaOrg.types).toEqual(['CreativeWork']);
    expect(system.schemaOrg.relationshipMap).toEqual({ manufacturer: 'producer' });
  });

  test('theme maps parents → isPartOf', () => {
    expect(theme.schemaOrg.relationshipMap).toEqual({ parents: 'isPartOf' });
  });
});
