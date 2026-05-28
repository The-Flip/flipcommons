import { describe, expect, test } from 'vitest';
import { buildSchemaOrgNode, buildEntityJsonLd, type EntityBaseFacts } from './schema-org';
import type { ModelFrontendInfo } from './types';
import { creditRole, theme } from './index';

const ORIGIN = 'https://flipcommons.org';
const PAGE = new URL(`${ORIGIN}/themes/fantasy`);

function entity(over: Partial<EntityBaseFacts> = {}): EntityBaseFacts {
  return {
    name: 'Fantasy',
    public_id: 'fantasy',
    description: { text: '', html: '', plain: 'Dragons and wizards.', citations: [] },
    ...over,
  };
}

function info(
  schemaOrg: ModelFrontendInfo<EntityBaseFacts>['schemaOrg'],
  entityType: ModelFrontendInfo<EntityBaseFacts>['entityType'] = 'theme',
): ModelFrontendInfo<EntityBaseFacts> {
  return { entityType, schemaOrg };
}

describe('buildSchemaOrgNode', () => {
  test('single type emits @type as a string', () => {
    const node = buildSchemaOrgNode(entity(), info({ types: ['DefinedTerm'] }), PAGE);
    expect(node['@type']).toBe('DefinedTerm');
    expect(node.name).toBe('Fantasy');
    expect(node.description).toBe('Dragons and wizards.');
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

  test('description is omitted when description is null', () => {
    const node = buildSchemaOrgNode(
      entity({ description: null }),
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

describe('per-model declarations', () => {
  test('theme is a DefinedTerm', () => {
    expect(theme.entityType).toBe('theme');
    expect(theme.schemaOrg.types).toEqual(['DefinedTerm']);
  });

  test('credit-role is an Occupation', () => {
    expect(creditRole.entityType).toBe('credit-role');
    expect(creditRole.schemaOrg.types).toEqual(['Occupation']);
  });
});
