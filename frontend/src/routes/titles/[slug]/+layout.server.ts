import { loadEntityPage } from '$lib/entity-page-loader.server';
import { title, model } from '$lib/entities';
import { buildSchemaOrgNode } from '$lib/entities/schema-org';
import { jsonLdGraph, breadcrumbList, absolutize, type JsonLdNode } from '$lib/components/jsonld';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/title/{public_id}', 'Title');

  const graph: JsonLdNode[] = [buildSchemaOrgNode(profile, title, event.url)];

  // Title.workExample → its Model(s): bespoke, since `machines` is a reverse
  // relation (not in `_meta`, so the generic relationshipMap walk can't reach
  // it). The `@id`s are dereferenceable via /models/{public_id} even when the
  // Model node isn't embedded below (multi-Model titles).
  const workExample = profile.machines.map((m) => ({
    '@id': absolutize(event.url, `/models/${m.public_id}`),
  }));
  if (workExample.length > 0) {
    graph[0].workExample = workExample.length === 1 ? workExample[0] : workExample;
  }

  // Single-Model Title (one machine, no variants): embed the full Model node
  // so a crawler following the workExample `@id` resolves it in-graph.
  if (profile.model_detail) {
    graph.push(buildSchemaOrgNode(profile.model_detail, model, event.url));
  }

  graph.push(breadcrumbList(event.url, [{ label: 'Home', href: '/' }], profile.name));

  return { profile, jsonLd: jsonLdGraph(graph) };
};
